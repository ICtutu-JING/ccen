#!/usr/bin/env python3
"""Offline deployment regression checks. Never start a service or network probe."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools/render-linux.py"


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ccen-render-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "staging"
        self.arguments = [
            sys.executable, str(RENDERER),
            "--home", "/home/student",
            "--uid", "12345",
            "--expected-ip", "203.0.113.10",
            "--country", "US",
            "--anthropic-colo", "LAX",
            "--output", str(self.output),
        ]

    def run_renderer(self, arguments=None):
        return subprocess.run(arguments or self.arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_core_is_complete_and_lab_and_broker_are_opt_in(self):
        result = self.run_renderer()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.output / "render-manifest.json").read_text())
        self.assertFalse(manifest["lab_relays"])
        self.assertFalse(manifest["host_runner_enabled"])
        self.assertFalse((self.output / "systemd/ccen-host-runner.socket").exists())
        self.assertFalse((self.output / "bin/claude-ssh-fpga03").exists())
        self.assertTrue((self.output / "optional/host-runner/systemd/ccen-host-runner.socket").is_file())
        settings = json.loads((self.output / "config/vscode-machine-settings.json").read_text())
        self.assertFalse(settings["http.useLocalProxyConfiguration"])
        self.assertFalse(settings["claudeCode.useTerminal"])
        self.assertTrue(settings["http.proxyStrictSSL"])
        self.assertEqual(settings["http.noProxy"], ["localhost", "127.0.0.1", "::1"])
        required = {entry["path"] for entry in manifest["required_directories"]}
        self.assertIn("/home/student/.config/systemd/user.control", required)
        self.assertIn("/home/student/.local/share/systemd/user", required)
        installed = {entry["destination"] for entry in manifest["install_files"] if entry["installed_by_default"]}
        self.assertEqual(len(installed), 7)
        self.assertNotIn("/home/student/.local/bin/claude", installed)
        launcher = (self.output / "libexec/claude-net-launcher").read_text()
        self.assertIn('if [[ "0" == "1" ]]', launcher)
        self.assertIn('/run/user/12345', launcher)
        self.assertIn('/home/student/.local/libexec/claude-net-pid1.py', launcher)
        self.assertIn('UPSTREAM_PORTS = (7899,)', (self.output / "libexec/claude-ip-gate").read_text())
        self.assertIn('"$upstream_proxy" == "http://127.0.0.1:7899"', (self.output / "bin/claude-ip-guard").read_text())
        for name, details in manifest["files"].items():
            payload = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), details["sha256"])
            # The runtime's deliberate unresolved-token guard uses the prefix;
            # full template tokens must all have disappeared.
            self.assertNotRegex(payload.decode(), r"__CCEN_[A-Z0-9_]+__")

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_text("untouched")
        result = self.run_renderer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "untouched")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_missing_expected_ip_is_rejected_before_writing(self):
        args = list(self.arguments)
        position = args.index("--expected-ip")
        del args[position:position + 2]
        self.assertNotEqual(self.run_renderer(args).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_injection_paths_and_invalid_values_are_rejected_without_writes(self):
        for flag, value in (
            ("--home", "/home/student/../other"),
            ("--home", "/home/$(touch-injection)"),
            ("--home", "/home/student with spaces"),
            ("--uid", "0"),
            ("--expected-ip", "proxy.example"),
            ("--country", "U;"),
            ("--anthropic-colo", "LAX;"),
            ("--output", "/home/student/.config/ccen-new-staging"),
        ):
            with self.subTest(flag=flag, value=value):
                args = list(self.arguments)
                args[args.index(flag) + 1] = value
                self.assertNotEqual(self.run_renderer(args).returncode, 0)
                self.assertFalse(self.output.exists())

    def test_partial_lab_configuration_is_rejected(self):
        result = self.run_renderer(self.arguments + ["--enable-lab-relays", "--ssh-user", "student"])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_explicit_lab_mapping_renders_only_supplied_addresses(self):
        arguments = self.arguments + [
            "--enable-lab-relays", "--lab-hostname", "lab-host.example",
            "--ssh-user", r"DOMAIN\student", "--ssh-identity", "/home/student/.ssh/lab-key",
            "--ssh-known-hosts", "/home/student/.ssh/known_hosts",
        ]
        for offset, name in enumerate(("fpga01", "fpga02", "fpga03", "fpga05", "fpga06"), start=11):
            arguments.extend(("--lab-target", f"{name}=192.0.2.{offset}"))
        result = self.run_renderer(arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('TARGET_HOST = "192.0.2.13"', (self.output / "libexec/claude-fpga03-ssh-relay").read_text())
        self.assertIn(r"User=DOMAIN\student", (self.output / "bin/claude-ssh-fpga03").read_text())
        self.assertIn('if [[ "1" == "1" ]]', (self.output / "libexec/claude-net-launcher").read_text())
        self.assertTrue((self.output / "systemd/claude-lab-ssh-relay@.service").is_file())

    def test_unrendered_entrypoints_fail_before_network(self):
        for executable in (ROOT / "bin/ccen", ROOT / "bin/claude-ip-guard", ROOT / "libexec/claude-ip-gate"):
            command = [sys.executable if executable.name == "claude-ip-gate" else "bash", str(executable)]
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("render", result.stderr.lower())

    def runtime_fixture(self):
        """Rendered scripts + fake bwrap in /tmp; no namespace/service/network use."""
        home = self.directory / "home"
        home.mkdir()
        args = list(self.arguments)
        args[args.index("--home") + 1] = str(home)
        result = self.run_renderer(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.output / "render-manifest.json").read_text())
        for entry in manifest["required_directories"]:
            Path(entry["path"]).mkdir(parents=True, exist_ok=True)
        for entry in manifest["install_files"]:
            if entry["installed_by_default"]:
                shutil.copyfile(self.output / entry["source"], entry["destination"])
                Path(entry["destination"]).chmod(int(entry["mode"], 8))
        runtime = self.directory / "runtime"
        gate = runtime / "claude-ip-gate"
        gate.mkdir(parents=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(gate / "proxy.sock"))
        self.addCleanup(server.close)
        capture = self.directory / "captured-argv.json"
        fake_bwrap = self.directory / "fake-bwrap"
        fake_bwrap.write_text(
            "#!/usr/bin/env python3\nimport json,os,sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CCEN_CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
            "print('CHILD_STDOUT')\nprint('CHILD_STDERR', file=sys.stderr)\n"
        )
        fake_bwrap.chmod(0o755)
        launcher = home / ".local/libexec/claude-net-launcher"
        launcher.write_text(launcher.read_text().replace("/run/user/12345", str(runtime)).replace("/usr/bin/bwrap", str(fake_bwrap)))
        executable = home / ".local/share/claude/versions/test-native"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        cli = home / ".local/bin/claude"
        cli.symlink_to(executable)
        passwd = runtime / "claude-net-passwd.test"
        passwd.write_text("student:x:12345:12345::/home/student:/bin/bash\n")
        passwd.chmod(0o600)
        cwd = self.directory / "workspace literal $HOME"
        cwd.mkdir()
        argfile = runtime / "claude-net-argv.test"
        argv = [str(cwd), str(passwd), str(cli), "--literal", "$HOME", "a b"]
        argfile.write_bytes(b"\0".join(item.encode() for item in argv) + b"\0")
        argfile.chmod(0o600)
        environment = os.environ | {"HOME": str(home), "CCEN_CAPTURE": str(capture)}
        return home, runtime, launcher, argfile, capture, environment

    def test_launcher_supports_native_cli_symlink_and_preserves_protocol_and_argv(self):
        home, runtime, launcher, argfile, capture, environment = self.runtime_fixture()
        config = home / ".config/ccen"
        (config / "ccen.env").write_text("do not expose this\n")
        (config / "host-runner.json").write_text("{}\n")
        state = home / ".local/state/ccen/host-jobs"
        state.mkdir(parents=True)
        result = subprocess.run(["bash", str(launcher), str(argfile)], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "CHILD_STDOUT\n")
        self.assertEqual(result.stderr, "CHILD_STDERR\n")
        argv = json.loads(capture.read_text())
        self.assertEqual(argv[-3:], ["--literal", "$HOME", "a b"])
        self.assertFalse(argfile.exists())
        for directory in (".local/libexec", ".config/ccen", ".config/systemd/user", ".config/systemd/user.control", ".local/share/systemd/user"):
            path = str(home / directory)
            self.assertIn(["--ro-bind", path, path], [argv[index:index + 3] for index in range(len(argv) - 2)])
        self.assertIn(["--ro-bind", "/dev/null", str(config / "ccen.env")], [argv[index:index + 3] for index in range(len(argv) - 2)])
        self.assertIn(["--tmpfs", str(state)], [argv[index:index + 2] for index in range(len(argv) - 1)])

    def test_launcher_rejects_missing_empty_control_directory(self):
        home, _runtime, launcher, argfile, capture, environment = self.runtime_fixture()
        missing = home / ".config/systemd/user.control"
        missing.rmdir()
        result = subprocess.run(["bash", str(launcher), str(argfile)], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("create it during installation", result.stderr)
        self.assertFalse(missing.exists())
        self.assertFalse(capture.exists())

    def test_launcher_rejects_symlinked_private_control_file_without_exposing_contents(self):
        home, _runtime, launcher, argfile, capture, environment = self.runtime_fixture()
        private = self.directory / "private-config"
        private.write_text("SECRET_SENTINEL_NEVER_PRINT\n")
        (home / ".config/ccen/ccen.env").symlink_to(private)
        result = subprocess.run(["bash", str(launcher), str(argfile)], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("contains a symlink", result.stderr)
        self.assertNotIn("SECRET_SENTINEL_NEVER_PRINT", result.stderr)
        self.assertFalse(capture.exists())

    def test_cli_refuses_inherited_proxy_without_printing_its_secret(self):
        home, _runtime, _launcher, _argfile, _capture, environment = self.runtime_fixture()
        environment["HTTPS_PROXY"] = "http://private-user:SECRET_SENTINEL_NEVER_PRINT@127.0.0.1:1111"
        result = subprocess.run(["bash", str(home / ".local/bin/ccen")], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTPS_PROXY=<已设置>", result.stdout)
        self.assertNotIn("SECRET_SENTINEL_NEVER_PRINT", result.stdout + result.stderr)

    def test_sandbox_suppresses_guard_stdout_and_preserves_child_output_and_exit(self):
        home, runtime, _launcher, _argfile, _capture, environment = self.runtime_fixture()
        _argfile.unlink()
        (runtime / "claude-net-passwd.test").unlink()
        sandbox = home / ".local/bin/claude-net-sandbox"
        sandbox.write_text(sandbox.read_text().replace("/run/user/12345", str(runtime)))
        guard = home / ".local/bin/claude-ip-guard"
        guard.write_text("#!/bin/sh\nprintf 'GUARD_STATUS_MUST_BE_SUPPRESSED\\n'\nprintf 'guard diagnostic\\n' >&2\n")
        guard.chmod(0o755)
        fake_commands = self.directory / "fake-commands"
        fake_commands.mkdir()
        scripts = {
            "id": "#!/bin/sh\nprintf '12345\\n'\n",
            "getent": f"#!/bin/sh\nprintf 'student:x:12345:12345::{home}:/bin/bash\\n'\n",
            "systemd-run": "#!/bin/sh\nprintf 'CHILD_STDOUT\\n'\nprintf 'CHILD_STDERR\\n' >&2\nexit 17\n",
        }
        for name, source in scripts.items():
            command = fake_commands / name
            command.write_text(source)
            command.chmod(0o755)
        environment["PATH"] = str(fake_commands) + os.pathsep + os.environ["PATH"]
        result = subprocess.run(["bash", str(sandbox), str(home / ".local/bin/claude")], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, "CHILD_STDOUT\n")
        self.assertEqual(result.stderr, "guard diagnostic\nCHILD_STDERR\n")
        self.assertFalse(list(runtime.glob("claude-net-argv.*")))
        self.assertFalse(list(runtime.glob("claude-net-passwd.*")))

    def test_cli_probes_pin_proxy_and_protocol_despite_cloudflare_pop_difference(self):
        home, _runtime, _launcher, _argfile, _capture, environment = self.runtime_fixture()
        fake_commands = self.directory / "fake-commands"
        fake_commands.mkdir()
        calls = self.directory / "curl-calls.jsonl"
        fake_curl = fake_commands / "curl"
        fake_curl.write_text(
            "#!/usr/bin/env python3\nimport json,os,sys\n"
            "with open(os.environ['CCEN_CURL_CALLS'],'a') as stream: stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
            "url=sys.argv[-1]\n"
            "if url=='https://api.ipify.org': print('203.0.113.10')\n"
            "elif url=='https://www.cloudflare.com/cdn-cgi/trace': print('ip=203.0.113.10\\nloc=US\\ncolo=IAD')\n"
            "elif url=='https://api.anthropic.com/': print('404')\n"
            "else: raise SystemExit(99)\n"
        )
        fake_curl.chmod(0o755)
        guard = home / ".local/bin/claude-ip-guard"
        guard.write_text("#!/bin/sh\nprintf '[OK] fixture guard\\n'\n")
        guard.chmod(0o755)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            environment.pop(key, None)
        environment["PATH"] = str(fake_commands) + os.pathsep + os.environ["PATH"]
        environment["CCEN_CURL_CALLS"] = str(calls)
        result = subprocess.run(["bash", str(home / ".local/bin/ccen")], input="q\n", env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("所有安全检查通过", result.stdout)
        self.assertNotIn("singapore-env.sh", (home / ".local/bin/ccen").read_text())
        probes = [json.loads(line) for line in calls.read_text().splitlines()]
        self.assertEqual(len(probes), 3)
        for argv in probes:
            self.assertEqual(argv[0], "--disable")
            self.assertEqual(argv[argv.index("--noproxy") + 1], "")
            self.assertEqual(argv[argv.index("--proxy") + 1], "http://127.0.0.1:17898")
            self.assertEqual(argv[argv.index("--proto") + 1], "=https")
            self.assertIn("--max-time", argv)

    def test_pid1_errors_use_stderr_and_never_protocol_stdout(self):
        result = subprocess.run([sys.executable, str(ROOT / "libexec/claude-net-pid1.py"), "/bin/true"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 70)
        self.assertEqual(result.stdout, "")
        self.assertIn("must run as PID 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
