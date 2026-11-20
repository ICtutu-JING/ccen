#!/usr/bin/env python3
"""Render explicitly configured Linux deployment files into a new staging tree.

This tool never installs files, starts services, or reads private configuration.
The source is an allowlist of repository templates, not a copy of the local user.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"__CCEN_[A-Z0-9_]+__")
LAB_NAMES = ("fpga01", "fpga02", "fpga03", "fpga05", "fpga06")
CORE = (
    "bin/ccen",
    "bin/claude-ip-guard",
    "bin/claude-net-sandbox",
    "libexec/claude-ip-gate",
    "libexec/claude-net-launcher",
    "libexec/claude-net-pid1.py",
    "systemd/claude-ip-gate.service",
)
LAB = (
    *(f"bin/claude-ssh-{name}" for name in (*LAB_NAMES, "fpga04")),
    "bin/claude-ssh-lab",
    "libexec/claude-fpga03-ssh-relay",
    "libexec/claude-fpga04-ssh-relay",
    "libexec/claude-lab-ssh-relay",
    "systemd/claude-fpga03-ssh-relay.service",
    "systemd/claude-fpga04-ssh-relay.service",
    "systemd/claude-lab-ssh-relay@.service",
)
BROKER = (
    "bin/ccen-host-run",
    "libexec/ccen-host-runner",
    "libexec/ccen-host-job",
    "systemd/ccen-host-runner.service",
    "systemd/ccen-host-runner.socket",
    "config/host-runner.json",
)


def safe_path(value: str, description: str) -> str:
    # Values enter shell, Python, JSON, and systemd syntax. Restrict to a common
    # literal subset rather than escaping differently in each target language.
    path = PurePosixPath(value)
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
        or value.startswith("//")
        or value == "/"
        or ".." in path.parts
        or str(path) != value
    ):
        raise ValueError(f"{description} must be a normalized absolute path without spaces or shell metacharacters")
    return value


def ipv4(value: str, description: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as error:
        raise ValueError(f"{description} must be an IPv4 address") from error
    if address.is_unspecified or address.is_multicast:
        raise ValueError(f"{description} cannot be an unspecified or multicast address")
    return str(address)


def configuration(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, Any]]:
    home = safe_path(args.home, "--home")
    if not 1 <= args.uid < 2**31:
        raise ValueError("--uid must be a non-root positive UID below 2^31")
    expected_ip = ipv4(args.expected_ip, "--expected-ip")
    country = args.country.upper()
    colo = args.anthropic_colo.upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("--country must be a two-letter country code")
    if not re.fullmatch(r"[A-Z]{3}", colo):
        raise ValueError("--anthropic-colo must be a three-letter Cloudflare POP code")

    lab_options = (args.lab_hostname, args.ssh_user, args.ssh_identity, args.ssh_known_hosts, args.lab_target)
    if not args.enable_lab_relays and any(lab_options):
        raise ValueError("lab options require --enable-lab-relays")

    targets: dict[str, str] = {}
    hostname = "lab-host.invalid"
    ssh_user = "lab-user"
    identity = home + "/.ssh/id_ed25519_lab"
    known_hosts = home + "/.ssh/known_hosts"
    if args.enable_lab_relays:
        if not all((args.lab_hostname, args.ssh_user, args.ssh_identity, args.ssh_known_hosts)):
            raise ValueError("lab mode requires --lab-hostname, --ssh-user, --ssh-identity, and --ssh-known-hosts")
        hostname = args.lab_hostname
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", hostname):
            raise ValueError("--lab-hostname contains unsupported characters")
        ssh_user = args.ssh_user
        if not re.fullmatch(r"[A-Za-z0-9_.@\\-]+", ssh_user):
            raise ValueError("--ssh-user contains unsupported characters")
        identity = safe_path(args.ssh_identity, "--ssh-identity")
        known_hosts = safe_path(args.ssh_known_hosts, "--ssh-known-hosts")
        for item in args.lab_target:
            name, separator, address = item.partition("=")
            if not separator or name not in LAB_NAMES or name in targets:
                raise ValueError("each --lab-target must be a unique fpga01/02/03/05/06=IPv4 mapping")
            targets[name] = ipv4(address, "--lab-target")
        if set(targets) != set(LAB_NAMES):
            raise ValueError("lab mode requires explicit --lab-target values for fpga01, fpga02, fpga03, fpga05, fpga06")

    values = {
        "HOME": home,
        "UID": str(args.uid),
        "EXPECTED_IP": expected_ip,
        "COUNTRY": country,
        "ANTHROPIC_COLO": colo,
        "ENABLE_LAB_RELAYS": "1" if args.enable_lab_relays else "0",
        "LAB_HOSTNAME": hostname,
        "SSH_USER": ssh_user,
        "SSH_IDENTITY": identity,
        "SSH_KNOWN_HOSTS": known_hosts,
        **{name.upper() + "_IP": address for name, address in targets.items()},
    }
    manifest: dict[str, Any] = {
        "version": 1,
        "home": home,
        "uid": args.uid,
        "expected_ip": expected_ip,
        "country": country,
        "anthropic_colo": colo,
        "lab_relays": args.enable_lab_relays,
        "host_runner_enabled": False,
        "note": "Staging only. No files installed and no services started.",
    }
    if args.enable_lab_relays:
        manifest["lab"] = {
            "hostname": hostname,
            "ssh_user": ssh_user,
            "identity_path": identity,
            "known_hosts_path": known_hosts,
            "targets": targets,
        }
    return {f"__CCEN_{key}__": value for key, value in values.items()}, manifest


def validate_source(payload: str, filename: str) -> None:
    if TOKEN.search(payload):
        raise ValueError(f"unresolved configuration token in {filename}")
    if payload.startswith("#!/usr/bin/env bash"):
        checked = subprocess.run(
            ["bash", "-n"], input=payload, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if checked.returncode:
            raise ValueError(f"rendered shell syntax is invalid in {filename}: {checked.stderr.strip()}")
    elif payload.startswith("#!/usr/bin/env python3"):
        ast.parse(payload, filename=filename)
    elif filename.endswith(".json"):
        json.loads(payload)


def render(args: argparse.Namespace) -> Path:
    substitutions, manifest = configuration(args)
    output = Path(args.output).expanduser().absolute()
    resolved_output = output.resolve()
    target_home = Path(args.home).resolve()
    protected = [target_home, Path("/run/user")]
    protected.extend(target_home / name for name in (".local", ".config", ".ssh", "bin"))
    if resolved_output == target_home or any(
        resolved_output == path or path in resolved_output.parents
        for path in protected[1:]
    ):
        raise ValueError("--output must be a staging directory outside installed .local/.config/.ssh/bin and /run/user paths")
    if output.exists() or output.is_symlink():
        raise ValueError("--output must name a new, nonexistent staging directory")
    if not output.parent.is_dir():
        raise ValueError("the staging directory's parent must already exist")
    # Source allowlist prevents accidentally packaging credentials, logs, or any
    # newly added unrelated file. Read and validate everything before writing.
    sources = [(name, name) for name in CORE]
    if args.enable_lab_relays:
        sources.extend((name, name) for name in LAB)
    sources.extend((name, "optional/host-runner/" + name) for name in BROKER)
    prepared: dict[str, tuple[str, int, str]] = {}
    for source_name, destination_name in sources:
        source = REPOSITORY / source_name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"repository template is missing or is a symlink: {source_name}")
        original = source.read_text(encoding="utf-8")
        payload = original
        for token, value in substitutions.items():
            payload = payload.replace(token, value)
        validate_source(payload, destination_name)
        mode = 0o755 if payload.startswith("#!") else 0o600 if source_name.endswith(".json") else 0o644
        prepared[destination_name] = (payload, mode, hashlib.sha256(original.encode()).hexdigest())

    settings = {
        "http.proxy": "http://127.0.0.1:17898",
        "http.proxySupport": "override",
        "http.proxyStrictSSL": True,
        "http.useLocalProxyConfiguration": False,
        "http.noProxy": ["localhost", "127.0.0.1", "::1"],
        "claudeCode.useTerminal": False,
        "claudeCode.claudeProcessWrapper": args.home + "/.local/bin/claude-net-sandbox",
        "claudeCode.environmentVariables": [
            {"name": key, "value": value}
            for key, value in {
                "HTTP_PROXY": "http://127.0.0.1:17898",
                "HTTPS_PROXY": "http://127.0.0.1:17898",
                "http_proxy": "http://127.0.0.1:17898",
                "https_proxy": "http://127.0.0.1:17898",
                "NO_PROXY": "localhost,127.0.0.1,::1",
                "no_proxy": "localhost,127.0.0.1,::1",
                "DISABLE_ERROR_REPORTING": "1",
                "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
            }.items()
        ],
    }
    prepared["config/vscode-machine-settings.json"] = (json.dumps(settings, indent=2) + "\n", 0o600, "generated")
    manifest["files"] = {
        name: {"sha256": hashlib.sha256(payload.encode()).hexdigest(), "template_sha256": template_hash}
        for name, (payload, _mode, template_hash) in sorted(prepared.items())
    }
    manifest["required_directories"] = [
        {"path": args.home + "/" + name, "mode": mode}
        for name, mode in (
            (".local/bin", "0755"),
            (".local/libexec", "0755"),
            (".local/lib/locale", "0755"),
            (".config/ccen", "0700"),
            (".config/systemd/user", "0700"),
            (".config/systemd/user.control", "0700"),
            (".local/share/systemd/user", "0700"),
        )
    ]
    destination_directories = {
        "bin": ".local/bin", "libexec": ".local/libexec",
        "systemd": ".config/systemd/user", "config": ".config/ccen",
    }
    manifest["install_files"] = []
    for source_name, destination_name in sources:
        group, basename = source_name.split("/", 1)
        component = "host-runner" if destination_name.startswith("optional/") else "lab" if source_name in LAB else "core"
        manifest["install_files"].append({
            "source": destination_name,
            "destination": args.home + "/" + destination_directories[group] + "/" + basename,
            "mode": f"{prepared[destination_name][1]:04o}",
            "component": component,
            "installed_by_default": component == "core",
        })

    output.mkdir(mode=0o700)
    try:
        for name, (payload, mode, _template_hash) in prepared.items():
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_text(payload, encoding="utf-8")
            destination.chmod(mode)
        manifest_path = output / "render-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_path.chmod(0o600)
    except BaseException:
        shutil.rmtree(output)
        raise
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="target user's absolute Linux home")
    parser.add_argument("--uid", required=True, type=int, help="target user's numeric non-root UID")
    parser.add_argument("--expected-ip", required=True, help="your independently verified fixed IPv4 exit")
    parser.add_argument("--country", required=True, help="expected two-letter Cloudflare country")
    parser.add_argument("--anthropic-colo", required=True, help="expected three-letter Anthropic CF-Ray POP")
    parser.add_argument("--output", required=True, help="new staging directory; never an installation prefix")
    parser.add_argument("--enable-lab-relays", action="store_true", help="include optional trusted SSH host relays")
    parser.add_argument("--lab-hostname", help="hostname condition for relay units")
    parser.add_argument("--ssh-user", help="your SSH login, including domain prefix if required")
    parser.add_argument("--ssh-identity", help="absolute path to your own SSH private key; contents are never read")
    parser.add_argument("--ssh-known-hosts", help="absolute path to your independently verified known_hosts")
    parser.add_argument("--lab-target", action="append", default=[], help="repeat for each remote host: fpga03=192.0.2.13")
    return parser.parse_args()


def main() -> int:
    try:
        output = render(parse_args())
    except (ValueError, OSError, SyntaxError) as error:
        print(f"render-linux: {error}", file=sys.stderr)
        return 2
    print(f"Rendered staging tree: {output}")
    print("No installed files or services were changed. Review docs/linux.md before installation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
