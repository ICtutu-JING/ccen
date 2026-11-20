"""Offline contract tests: no sockets, daemon startup, or real network calls."""
from __future__ import annotations

import asyncio
from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import io
import sys
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("ccen_gate_under_test", str(ROOT / "libexec/claude-ip-gate"))
spec = importlib.util.spec_from_loader(loader.name, loader)
gate = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = gate
with patch.dict(os.environ, {
    "CLAUDE_GUARD_EXPECTED_IP": "192.0.2.42",
    "CLAUDE_GUARD_EXPECTED_CF_COUNTRY": "US",
    "CLAUDE_GUARD_EXPECTED_CF_COLO": "LAX",
}):
    loader.exec_module(gate)


class GateContractTests(unittest.IsolatedAsyncioTestCase):
    async def run_monitor_scenario(self, results):
        monitor = gate.ProxyGate()
        states = []

        async def opened():
            monitor.allowed = True

        async def closed():
            monitor.allowed = False

        async def advance(_delay):
            if len(states) >= len(results) + 1:  # includes initial checking state
                monitor.stop_event.set()

        with patch.object(gate, "select_healthy_upstream", AsyncMock(side_effect=results)), \
             patch.object(gate, "write_state", side_effect=lambda status, result, **fields: states.append((status, fields))), \
             patch.object(monitor, "open_listeners", opened), \
             patch.object(monitor, "close_gate", closed), \
             patch.object(monitor, "listeners_active", side_effect=lambda: monitor.allowed), \
             patch.object(monitor, "wait_for_trigger", advance), \
             patch("sys.stdout", new_callable=io.StringIO), \
             patch("sys.stderr", new_callable=io.StringIO):
            await monitor.run()
        return states[1:-1]  # discard checking and final stopped

    async def test_two_transient_failures_preserve_listeners_then_third_blocks(self):
        good = gate.CheckResult(True, "all checks passed", upstream_port=7899)
        timeout = gate.CheckResult(False, "curl subprocess timeout")
        states = await self.run_monitor_scenario([good, timeout, timeout, timeout])
        self.assertEqual([status for status, _fields in states], ["allowed", "allowed", "allowed", "blocked"])
        self.assertEqual([fields["tcp_listener"] for _status, fields in states], ["active", "active", "active", "inactive"])
        self.assertIn("transient", states[1][1]["reason"])

    async def test_identity_mismatch_blocks_on_first_completed_check(self):
        good = gate.CheckResult(True, "all checks passed", upstream_port=7899)
        mismatch = gate.CheckResult(False, "ipify mismatch: unexpected address")
        states = await self.run_monitor_scenario([good, mismatch])
        self.assertEqual([status for status, _fields in states], ["allowed", "blocked"])
        self.assertEqual(states[-1][1]["tcp_listener"], "inactive")

    async def test_rule_based_port_never_becomes_fallback(self):
        self.assertEqual(gate.UPSTREAM_PORTS, (7899,))
        fail = gate.CheckResult(False, "unavailable", upstream_port=7899)
        with patch.object(gate, "perform_checks", AsyncMock(return_value=fail)) as probe:
            result = await gate.select_healthy_upstream(preferred_port=7898)
        self.assertFalse(result.ok)
        self.assertEqual(result.upstream_port, 0)
        probe.assert_awaited_once_with(7899)

    async def test_exact_ip_required(self):
        with patch.object(gate, "run_curl", AsyncMock(return_value=(0, "192.0.2.43", ""))):
            result = await gate.probe_ipify(7899)
        self.assertFalse(result.ok)
        self.assertIn("mismatch", result.reason)

    async def test_cloudflare_pop_is_observed_but_country_is_enforced(self):
        for country, expected in (("US", True), ("SG", False)):
            with self.subTest(country=country):
                output = f"ip=192.0.2.42\nloc={country}\ncolo=SJC\n"
                with patch.object(gate, "run_curl", AsyncMock(return_value=(0, output, ""))):
                    result = await gate.probe_cloudflare(7899)
                self.assertEqual(result.ok, expected)
                self.assertEqual(result.details["colo"], "SJC")

    async def test_anthropic_pop_required_even_when_network_responds(self):
        for colo, expected in (("LAX", True), ("SJC", False)):
            with self.subTest(colo=colo):
                output = f"HTTP/2 404\r\ncf-ray: test123-{colo}\r\n__CLAUDE_GUARD_HTTP_STATUS__:404\n"
                with patch.object(gate, "run_curl", AsyncMock(return_value=(0, output, ""))):
                    result = await gate.probe_anthropic(7899)
                self.assertEqual(result.ok, expected)

    async def test_anthropic_missing_edge_identity_is_rejected(self):
        for output in ("__CLAUDE_GUARD_HTTP_STATUS__:404\n", "cf-ray: test-LAX\n__CLAUDE_GUARD_HTTP_STATUS__:000\n"):
            with patch.object(gate, "run_curl", AsyncMock(return_value=(0, output, ""))):
                self.assertFalse((await gate.probe_anthropic(7899)).ok)

    async def test_all_independent_probes_must_pass(self):
        good_ip = gate.Probe(True, "192.0.2.42")
        good_cf = gate.Probe(True, details={"ip": "192.0.2.42", "country": "US", "colo": "SJC"})
        bad_edge = gate.Probe(False, reason="Anthropic edge mismatch")
        with patch.object(gate, "probe_ipify", AsyncMock(return_value=good_ip)), \
             patch.object(gate, "probe_cloudflare", AsyncMock(return_value=good_cf)), \
             patch.object(gate, "probe_anthropic", AsyncMock(return_value=bad_edge)):
            result = await gate.perform_checks(7899)
        self.assertFalse(result.ok)
        self.assertIn("Anthropic edge mismatch", result.reason)


if __name__ == "__main__":
    unittest.main()
