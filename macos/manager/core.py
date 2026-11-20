from __future__ import annotations
import collections
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlencode

from deployment import DATA, ROOT, DEPLOYMENT_FILE, EXPECTED_IP, EXPECTED_COUNTRY, EXPECTED_COLO, RESIDENTIAL_PORT
from processes import AttachedProcess, guard_processes
from remote_connection import RemoteConnection

HIDDEN = 0


class Manager:
    def __init__(self, prompt, data=DATA):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.guard_dir = self.data / 'guard'
        self.guard_dir.mkdir(exist_ok=True)
        self.settings_file = self.data / 'settings.json'
        self.settings = json.loads(self.settings_file.read_text()) if self.settings_file.exists() else dict(guard_enabled=False, startup=False)
        self.lock = threading.RLock()
        self.actions = threading.Lock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.guard_process = None
        self.guard_next_try = 0
        self.guard_error = ''
        self.local_ok = False
        self.events = collections.deque(maxlen=120)
        self.files = []
        self.thread = None
        self.connection = RemoteConnection(self.log, prompt)
        self.log('应用已就绪。连接服务器后，在桌面应用中选择 ccen 即可工作。')

    def start(self):
        pids = guard_processes(self.data)
        if len(pids) > 1:
            raise RuntimeError('发现多个本机守卫，请先结束重复实例。')
        if pids:
            self.guard_process = AttachedProcess(pids[0])
            self.log('已接管本机守卫，现有连接继续运行。')
        self.thread = threading.Thread(target=self.monitor, daemon=True)
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return dict(settings=dict(self.settings), local_ok=self.local_ok,
                        guard=self.guard_status(), connection=self.connection.snapshot(),
                        events=list(self.events), checked_at=time.strftime('%H:%M:%S'),
                        expected_ip=EXPECTED_IP, expected_country=EXPECTED_COUNTRY,
                        expected_colo=EXPECTED_COLO)

    def monitor(self):
        while not self.closed.is_set():
            try:
                try:
                    with socket.create_connection(('127.0.0.1', RESIDENTIAL_PORT), timeout=1):
                        self.local_ok = True
                except OSError:
                    self.local_ok = False
                with self.actions:
                    if self.settings['guard_enabled']:
                        self._ensure_guard()
                if time.monotonic() - self.connection.last_check >= 30:
                    self.connection.check()
            except Exception as error:
                self.log('连接检查失败：'+str(error))
            self.wake.wait(3)
            self.wake.clear()

    def check_now(self):
        self.connection.last_check = 0
        self.wake.set()
        return dict(ok=True)

    def connect_server(self, host=None, user=None, port=None, account=None):
        if account is not None:
            try:
                self.connection.configure(host, user, port, account)
            except (OSError, RuntimeError, ValueError) as error:
                return dict(ok=False, error=str(error))
            host = user = port = None
        result = self.set_guard(True)
        if not result['ok']:
            return result
        return self.connection.connect(host, user, port)

    def disconnect_server(self):
        return self.connection.disconnect()

    def open_client(self, client):
        if not self.connection.state['connected']:
            return dict(ok=False, error='请先点击“连接服务器”。')
        if client == 'codex':
            subprocess.run(['/usr/bin/open', '-b', 'com.openai.codex'], check=True)
        elif client == 'claude':
            app = Path.home() / 'Applications/Claude.app'
            if not app.exists():
                app = Path('/Applications/Claude.app')
            if not app.exists():
                return dict(ok=False, error='请先安装 Claude 桌面版。')
            query = urlencode(dict(ssh_host='ccen', ssh_folder=self.connection.config['shared_home']))
            subprocess.run(['/usr/bin/open', '-a', str(app), 'claude://code/new?'+query], check=True)
        else:
            return dict(ok=False, error='未知应用。')
        return dict(ok=True)

    def open_logs(self):
        subprocess.run(['/usr/bin/open', str(self.data)], check=True)
        return dict(ok=True)

    def stop(self):
        self.closed.set()
        self.wake.set()
        result = self.connection.disconnect()
        if not result['ok']:
            raise RuntimeError(result['error'])
        with self.actions:
            if self.guard_process is not None:
                self._stop_owned(self.guard_process)
        for stream in self.files:
            stream.close()

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
        node = ROOT / 'runtime/node'
        if not node.exists():
            raise RuntimeError('应用缺少内置 Node 运行时，请重新安装完整应用目录')
        # The runtime copy keeps status and logs in the user's writable app-data folder.
        shutil.copytree(ROOT / 'resources/node_modules', self.guard_dir / 'node_modules', dirs_exist_ok=True)
        shutil.copyfile(ROOT / 'resources/guard.cjs', self.guard_dir / 'guard.cjs')
        shutil.copyfile(DEPLOYMENT_FILE, self.guard_dir / 'deployment.json')
        self.guard_process = self.launch([str(node), str(self.guard_dir / 'guard.cjs')], 'guard.log')
        self.guard_error = ''
        self.log('浏览器守卫已启动，正在核验固定住宅出口。')


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


    def set_startup(self, enabled):
        if not getattr(sys, 'frozen', False):
            return {'ok': False, 'error': '登录启动请在打包后的应用中设置'}
        agent = Path.home() / 'Library/LaunchAgents/com.ccen.connection-manager.plist'
        if enabled:
            agent.parent.mkdir(parents=True, exist_ok=True)
            application = Path(sys.executable).resolve().parents[2]
            with agent.open('wb') as stream:
                plistlib.dump({
                    'Label': 'com.ccen.connection-manager',
                    'ProgramArguments': ['/usr/bin/open', '-g', str(application), '--args', '--tray'],
                    'RunAtLoad': True,
                    'LimitLoadToSessionType': 'Aqua',
                }, stream)
        else:
            agent.unlink(missing_ok=True)
        self.settings['startup'] = bool(enabled)
        self.save()
        self.log('已设置登录 macOS 后在菜单栏启动。' if enabled else '已关闭登录启动。')
        return {'ok': True}


    @staticmethod
    def _stop_owned(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
