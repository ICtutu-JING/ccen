"""The 远端 Codex proxy connection owned by the tray application."""
import socket
import time


class CodexProxy:
    def __init__(self, ssh, host, launch, log):
        self.ssh = ssh
        self.host = host
        self.launch = launch
        self.log = log
        self.process = None
        self.next_try = 0
        self.failures = 0
        self.reconnects = 0
        self.local_ok = False
        self.remote = dict(verified=False, reason='正在检查 Codex 代理链路')
        self.error = ''
        self.external_pids = []

    def snapshot(self):
        return dict(owned=self.process is not None and self.process.poll() is None,
                    local_ok=self.local_ok, remote=dict(self.remote), error=self.error,
                    external=len(self.external_pids), reconnects=self.reconnects)

    def ensure(self, enabled, remote):
        try:
            with socket.create_connection(('127.0.0.1', 7897), timeout=1):
                self.local_ok = True
        except OSError:
            self.local_ok = False
        if self.process is not None:
            code = self.process.poll()
            if code is None:
                return
            self.process = None
            self.failures += 1
            self.next_try = time.monotonic() + min(60, 5 * 2 ** min(self.failures - 1, 4))
            self.error = f'Codex 隧道已断开（代码 {code}），等待自动重连'
            self.log(self.error)
            return
        if not enabled or not self.local_ok or time.monotonic() < self.next_try:
            return
        if self.external_pids or (remote.get('reachable') and 7897 in remote['ports']):
            self.error = '正在等待现有 Codex 隧道恢复或退出'
            return
        self.process = self.launch([str(self.ssh), '-NT', '-o', 'BatchMode=yes',
            '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-R', '127.0.0.1:7897:127.0.0.1:7897', self.host], 'codex-ssh.log')
        self.reconnects += 1
        self.error = ''
        self.log('已在后台建立 远端 Codex 代理隧道。')

    def update_remote(self, remote):
        current = remote.get('codex', dict(verified=False, reason=remote['reason']))
        if current != self.remote:
            self.log('Codex：' + current['reason'])
        self.remote = current
        if current['verified']:
            self.failures = 0
            self.error = ''
