from __future__ import annotations

import collections
import ctypes
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from codex_proxy import CodexProxy
from processes import AttachedProcess
from deployment import ROOT, DEPLOYMENT_FILE, HOST, EXPECTED_IP, EXPECTED_COUNTRY, EXPECTED_COLO, REMOTE_PATH

FORWARD = '127.0.0.1:7899:127.0.0.1:7899'
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
DATA = Path(os.environ.get('APPDATA', Path.home())) / 'ClaudeConnectionManager'
SSH = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32/OpenSSH/ssh.exe'
REMOTE_SCRIPT = r'''
import os, json, pathlib, re, signal, subprocess, time
listeners = subprocess.run(['ss','-lntpeH'], capture_output=True, text=True, check=True).stdout
released = []
for port in orphan_ports:
    line = next((line for line in listeners.splitlines() if f'127.0.0.1:{port} ' in line), None)
    if line is None:
        continue
    scope = re.search(r'cgroup:(/user.slice/user-\d+\.slice/session-\d+\.scope)', line)
    if scope is None:
        raise RuntimeError(f'无法定位 {port} 的专用 SSH 会话')
    pids = [int(pid) for pid in (pathlib.Path('/sys/fs/cgroup' + scope[1]) / 'cgroup.procs').read_text().split()]
    owners = []
    for pid in pids:
        proc = pathlib.Path('/proc') / str(pid)
        if proc.joinpath('comm').read_text().strip() != 'sshd':
            raise RuntimeError(f'{port} 所属会话还有其他任务，不能自动释放')
        uid = int(re.search(r'^Uid:\s+(\d+)', proc.joinpath('status').read_text(), re.M)[1])
        if uid == os.getuid():
            owners.append(pid)
    if len(owners) != 1:
        raise RuntimeError(f'无法唯一确认 {port} 的 SSH 转发进程')
    os.kill(owners[0], signal.SIGTERM)
    released.append(port)
if released:
    listeners = subprocess.run(['ss','-lntH'], capture_output=True, text=True, check=True).stdout
ports = sorted(set(int(p) for p in re.findall(r'127\.0\.0\.1:(\d+)\s', listeners)))
file = pathlib.Path('/run/user') / str(os.getuid()) / 'claude-ip-gate/status'
gate = dict(line.split('=',1) for line in file.read_text().splitlines() if '=' in line) if file.exists() else {}
codex = dict(verified=False, reason='远端 Codex 代理尚未连接')
if 7897 in ports:
    result = subprocess.run(['curl','-sS','-I','-o','/dev/null','--max-time','8',
        '--proxy','http://127.0.0.1:7897','-w','%{http_code} %{http_connect}',
        'https://chatgpt.com/backend-api/codex/responses'], capture_output=True, text=True)
    codex['verified'] = result.returncode == 0 and result.stdout.strip() == '405 200'
    codex['reason'] = 'Codex 代理可用，已连通 ChatGPT' if codex['verified'] else 'Codex 上游请求失败：' + (result.stderr.strip() or result.stdout.strip())
print(json.dumps({'ports': ports, 'gate': gate, 'codex': codex, 'released': released, 'epoch': time.time()}))
'''


def run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, creationflags=HIDDEN)


def local_proxy_available():
    try:
        with socket.create_connection(('127.0.0.1', 7899), timeout=1):
            return True
    except OSError:
        return False


def managed_processes():
    command = "Get-CimInstance Win32_Process -Filter \"Name='ssh.exe' OR Name='node.exe'\" | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    result = run(['powershell.exe', '-NoProfile', '-Command', command], timeout=12)
    if result.returncode:
        raise RuntimeError('无法读取本机 SSH 进程')
    rows = json.loads(result.stdout or '[]')
    if isinstance(rows, dict):
        rows = [rows]
    found = {7897: [], 7899: [], 'guard': []}
    for row in rows:
        text = row.get('CommandLine') or ''
        if row['Name'] == 'node.exe' and str(DATA / 'guard/guard.cjs').lower() in text.lower():
            found['guard'].append(int(row['ProcessId']))
        # Only standalone reverse forwards; never a VS Code -D shell.
        if (re.search(r'(?:^|\s)-NT(?:\s|$)', text)
                and re.search(r'\s' + re.escape(HOST) + r'\s*$', text)
                and not re.search(r'\s-[DLW]\s', text)):
            for port in (7897, 7899):
                forward = f'127.0.0.1:{port}:127.0.0.1:{port}'
                if re.search(r'\s-R\s+"?' + re.escape(forward) + r'"?(?:\s|$)', text):
                    found[port].append(int(row['ProcessId']))
    return found


def interpret_remote(payload):
    gate = payload['gate']
    fresh = 0 <= payload['epoch'] - float(gate.get('checked_epoch', '0')) <= 120
    identity_ok = (gate.get('ipify_ip') == EXPECTED_IP
                   and gate.get('cloudflare_ip') == EXPECTED_IP
                   and gate.get('cloudflare_country') == EXPECTED_COUNTRY)
    ports = payload['ports']
    verified = (fresh and identity_ok and gate.get('status') == 'allowed'
                and 17898 in ports and 7899 in ports)
    return dict(reachable=True, verified=verified, ports=ports, codex=payload['codex'],
                ip=gate.get('ipify_ip', '—'), region=gate.get('cloudflare_country', '—'),
                colo=gate.get('anthropic_colo', '—'), gate=gate.get('status', 'unknown'),
                checked_at=gate.get('checked_at', ''), fresh=fresh,
                reason=gate.get('reason', '远端守卫尚未报告状态'))


class Manager:
    def __init__(self, data=DATA):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.guard_dir = self.data / 'guard'
        self.guard_dir.mkdir(exist_ok=True)
        self.settings_file = self.data / 'settings.json'
        self.settings = ({'guard_enabled': False, 'ssh_reconnect': False, 'codex_reconnect': False, 'startup': False}
                         if not self.settings_file.exists()
                         else json.loads(self.settings_file.read_text(encoding='utf-8')))
        self.lock = threading.RLock()
        self.actions = threading.Lock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.guard_process = None
        self.tunnel_process = None
        self.guard_next_try = 0.0
        self.tunnel_next_try = 0.0
        self.failures = 0
        self.reconnect_count = 0
        self.local_ok = False
        self.external_pids = []
        self.remote = dict(reachable=False, verified=False, reason='正在检查 SSH 与远端守卫', ports=[])
        self.guard_error = ''
        self.tunnel_error = ''
        self.tunnel_log_offset = 0
        self.last_remote_check = 0.0
        self.events = collections.deque(maxlen=120)
        self.files = []
        self.thread = None
        self.codex = CodexProxy(SSH, HOST, self.launch, self.log)
        self.log('应用已就绪。关闭窗口后继续在托盘运行。')

    def log(self, message):
        entry = {'time': time.strftime('%H:%M:%S'), 'message': message}
        with self.lock:
            self.events.appendleft(entry)
            with (self.data / 'manager.log').open('a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

    def save(self):
        self.settings_file.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')

    def launch(self, args, logfile):
        stream = (self.data / logfile).open('a', encoding='utf-8')
        self.files.append(stream)
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                creationflags=HIDDEN, cwd=self.data)

    def start(self):
        existing = managed_processes()
        for key, owner, attribute in [('guard', self, 'guard_process'),
                                       (7899, self, 'tunnel_process'),
                                       (7897, self.codex, 'process')]:
            if len(existing[key]) > 1:
                raise RuntimeError(f'{key} 存在多个管理进程，请先处理重复实例')
            if existing[key]:
                setattr(owner, attribute, AttachedProcess(existing[key][0]))
                self.log(f'已接管现有 {key} 进程，连接保持运行。')
        self.thread = threading.Thread(target=self.monitor, daemon=True)
        self.thread.start()

    def guard_status(self):
        running = self.guard_process is not None and self.guard_process.poll() is None
        result = dict(running=running, verified=False, forwarding=False, reason=self.guard_error or '尚未启动',
                      ip='—', region='—', colo='—', checked_at='', active=0)
        status = self.guard_dir / 'status.json'
        if running and status.exists():
            try:
                item = json.loads(status.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                result['reason'] = '正在更新核验结果'
                return result
            if item.get('pid') == self.guard_process.pid:
                observed = item.get('observed') or {}
                from datetime import datetime
                checked = item.get('checkedAt')
                age = time.time() - datetime.fromisoformat(checked.replace('Z', '+00:00')).timestamp() if checked else float('inf')
                result.update(verified=bool(item.get('allowed') and item.get('reason') == 'verified' and 0 <= age <= 22
                                            and observed.get('ip') == EXPECTED_IP
                                            and observed.get('loc') == EXPECTED_COUNTRY
                                            and observed.get('colo') == EXPECTED_COLO),
                              forwarding=bool(item.get('allowed')),
                              reason=item.get('reason', 'not_verified'),
                              ip=observed.get('ip', '—'), region=observed.get('loc', '—'),
                              colo=observed.get('colo', '—'), checked_at=checked or '',
                              active=item.get('activeTunnels', 0))
        return result

    def snapshot(self):
        with self.lock:
            owned = self.tunnel_process is not None and self.tunnel_process.poll() is None
            return dict(settings=dict(self.settings), local_ok=self.local_ok, guard=self.guard_status(),
                        remote=dict(self.remote), tunnel=dict(owned=owned, external=len(self.external_pids),
                        reconnects=self.reconnect_count, error=self.tunnel_error,
                        next_retry=max(0, int(self.tunnel_next_try - time.monotonic()))),
                        codex=self.codex.snapshot(), events=list(self.events), checked_at=time.strftime('%H:%M:%S'),
                        expected_ip=EXPECTED_IP, expected_country=EXPECTED_COUNTRY, expected_colo=EXPECTED_COLO, host=HOST, data_path=str(self.data))

    def _ensure_guard(self):
        if self.guard_process is not None and self.guard_process.poll() is None:
            return
        if time.monotonic() < self.guard_next_try:
            return
        if self.guard_process is not None:
            self.guard_error = f'守卫已退出（代码 {self.guard_process.returncode}），等待重新启动'
            self.log(self.guard_error)
            self.guard_process = None
            self.guard_next_try = time.monotonic() + 10
            return
        node = ROOT / 'runtime/node.exe'
        if not node.exists():
            raise RuntimeError('应用缺少内置 Node 运行时，请重新安装完整应用目录')
        # The runtime copy keeps status and logs in the user's writable app-data folder.
        shutil.copytree(ROOT / 'resources/node_modules', self.guard_dir / 'node_modules', dirs_exist_ok=True)
        shutil.copyfile(ROOT / 'resources/guard.cjs', self.guard_dir / 'guard.cjs')
        shutil.copyfile(DEPLOYMENT_FILE, self.guard_dir / 'deployment.json')
        self.guard_process = self.launch([str(node), str(self.guard_dir / 'guard.cjs')], 'guard.log')
        self.guard_error = ''
        self.log('浏览器守卫已启动，正在核验固定住宅出口。')

    def _probe_remote(self):
        orphan_ports = []
        if self.settings['ssh_reconnect'] and not self.external_pids:
            orphan_ports.append(7899)
        if self.settings['codex_reconnect'] and not self.codex.external_pids:
            orphan_ports.append(7897)
        command = 'python3 -c ' + shlex.quote('orphan_ports = ' + repr(orphan_ports) + '\n' + REMOTE_SCRIPT)
        result = run([str(SSH), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', HOST, command], timeout=18)
        if result.returncode:
            text = result.stderr
            if 'Permission denied' in text:
                reason = 'SSH 身份验证失败；检查现有密钥和登录配置后再启用恢复'
            elif 'Host key verification failed' in text:
                reason = 'SSH 主机密钥验证失败；需要核对主机身份'
            else:
                reason = 'SSH 暂时无法连接；检查校园网或 VPN'
            return dict(reachable=False, verified=False, reason=reason, ports=[])
        payload = json.loads(result.stdout)
        for port in payload['released']:
            self.log(f'已释放远端 {port} 遗留的专用 SSH 会话，正在恢复连接。')
        return interpret_remote(payload)

    def _ensure_tunnel(self):
        now = time.monotonic()
        if self.tunnel_process is not None:
            code = self.tunnel_process.poll()
            if code is None:
                return
            self.tunnel_process = None
            self.failures += 1
            self.tunnel_next_try = now + min(60, 5 * (2 ** min(self.failures - 1, 4)))
            with (self.data / 'ssh.log').open('rb') as log:
                log.seek(self.tunnel_log_offset)
                tail = log.read().decode('utf-8', errors='replace')[-3000:]
            if 'Permission denied' in tail or 'Host key verification failed' in tail:
                self.settings['ssh_reconnect'] = False
                self.save()
                self.tunnel_error = 'SSH 身份验证失败，自动重试已暂停'
            else:
                self.tunnel_error = f'专用隧道已断开，将在 {int(self.tunnel_next_try - now)} 秒后重连'
            self.log(self.tunnel_error)
            return
        if now < self.tunnel_next_try or not self.local_ok:
            return
        if 7899 in self.remote.get('ports', []) and self.remote.get('reachable'):
            return
        if self.external_pids:
            self.tunnel_error = '正在等待现有专用 SSH 隧道恢复或退出'
            return
        log = self.data / 'ssh.log'
        self.tunnel_log_offset = log.stat().st_size if log.exists() else 0
        self.tunnel_process = self.launch([str(SSH), '-NT', '-o', 'BatchMode=yes',
            '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=3', '-o', 'ConnectTimeout=8', '-R', FORWARD, HOST], 'ssh.log')
        self.reconnect_count += 1
        self.tunnel_error = ''
        self.last_remote_check = 0
        self.log('已启动 远端 专用住宅代理隧道，等待远端核验。')

    def monitor(self):
        while not self.closed.is_set():
            try:
                self.local_ok = local_proxy_available()
                if time.monotonic() - self.last_remote_check >= 30:
                    try:
                        existing = managed_processes()
                        self.external_pids = existing[7899]
                        self.codex.external_pids = existing[7897]
                        remote = self._probe_remote()
                    except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as error:
                        remote = dict(reachable=False, verified=False, ports=[],
                                      reason='检查超时' if isinstance(error, subprocess.TimeoutExpired) else str(error))
                    with self.lock:
                        before = (self.remote.get('reachable'), self.remote.get('verified'), self.remote.get('reason'))
                        self.remote = remote
                    after = (remote.get('reachable'), remote.get('verified'), remote.get('reason'))
                    if before != after:
                        self.log('远端：' + ('住宅链及远端守卫核验通过' if remote.get('verified') else remote.get('reason', '等待核验')))
                    if remote.get('verified'):
                        self.failures = 0
                        self.tunnel_error = ''
                    self.codex.update_remote(remote)
                    self.last_remote_check = time.monotonic()
                with self.actions:
                    if self.closed.is_set():
                        break
                    if self.settings['guard_enabled']:
                        self._ensure_guard()
                    if self.settings['ssh_reconnect']:
                        self._ensure_tunnel()
                    self.codex.ensure(self.settings['codex_reconnect'], self.remote)
            except Exception as error:
                self.log('管理操作失败：' + str(error))
            self.wake.wait(3)
            self.wake.clear()

    def set_guard(self, enabled):
        with self.actions:
            self.settings['guard_enabled'] = bool(enabled)
            self.save()
            if enabled:
                self.guard_next_try = 0
                try:
                    self._ensure_guard()
                except Exception as error:
                    self.guard_error = str(error)
                    return {'ok': False, 'error': str(error)}
            elif self.guard_process is not None:
                self._stop_owned(self.guard_process)
                self.guard_process = None
                self.guard_error = ''
                self.log('浏览器守卫已停止；已接入该代理的浏览器会断网。')
        self.wake.set()
        return {'ok': True}

    def set_reconnect(self, enabled):
        with self.actions:
            self.settings['ssh_reconnect'] = bool(enabled)
            self.tunnel_next_try = 0
            self.failures = 0
            self.last_remote_check = 0
            self.save()
            self.log('已启用 远端 代理断线自动恢复。' if enabled else '已暂停自动恢复，当前 SSH 连接继续运行。')
        self.wake.set()
        return {'ok': True}

    def check_now(self):
        self.last_remote_check = 0
        self.wake.set()
        return {'ok': True}

    def set_codex_reconnect(self, enabled):
        with self.actions:
            self.settings['codex_reconnect'] = bool(enabled)
            self.codex.next_try = 0
            self.codex.failures = 0
            self.last_remote_check = 0
            self.save()
            self.log('已启用 Codex 后台自动重连。' if enabled else '已暂停 Codex 自动恢复，当前连接继续运行。')
        self.wake.set()
        return {'ok': True}

    def restart_owned_tunnel(self):
        with self.actions:
            if self.tunnel_process is None or self.tunnel_process.poll() is not None:
                return {'ok': False, 'error': '当前隧道由其他程序维持。启用自动恢复后，应用会在它退出时接续。'}
            self._stop_owned(self.tunnel_process)
            self.tunnel_process = None
            self.tunnel_next_try = 0
            self.last_remote_check = 0
            self.settings['ssh_reconnect'] = True
            self.save()
            self.log('本应用的专用代理隧道已关闭，正在重新建立。')
        self.wake.set()
        return {'ok': True}

    def set_startup(self, enabled):
        import winreg
        if not getattr(sys, 'frozen', False):
            return {'ok': False, 'error': '开机启动请在打包后的应用中设置'}
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if enabled:
                winreg.SetValueEx(key, 'ClaudeConnectionManager', 0, winreg.REG_SZ, f'"{sys.executable}" --tray')
            else:
                try:
                    winreg.DeleteValue(key, 'ClaudeConnectionManager')
                except FileNotFoundError:
                    pass
        self.settings['startup'] = bool(enabled)
        self.save()
        self.log('已设置登录 Windows 后在托盘启动。' if enabled else '已关闭开机启动。')
        return {'ok': True}

    def open_vscode(self):
        os.startfile(f'vscode://vscode-remote/ssh-remote+{HOST}{REMOTE_PATH}')
        return {'ok': True}

    def open_logs(self):
        os.startfile(str(self.data))
        return {'ok': True}

    @staticmethod
    def _stop_owned(process):
        if process.poll() is None:
            run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], timeout=8)
            process.wait(timeout=5)

    def stop(self):
        self.closed.set()
        self.wake.set()
        with self.actions:
            for process in (self.guard_process, self.tunnel_process, self.codex.process):
                if process is not None:
                    self._stop_owned(process)
        for stream in self.files:
            stream.close()
