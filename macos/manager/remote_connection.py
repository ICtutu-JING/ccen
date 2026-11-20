"""One GUI-managed SSH gateway for both desktop clients."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time

from deployment import ORDINARY_PORT, EXPECTED_IP, EXPECTED_COUNTRY, EXPECTED_COLO
from ssh_login import login

SSH = '/usr/bin/ssh'
DIRECTORY = Path.home() / '.ssh'
TARGET = DIRECTORY / 'ccen-target.json'
CONTROL = DIRECTORY / 'ccen-master.sock'
CONFIG = DIRECTORY / 'ccen.conf'
KNOWN_HOSTS = DIRECTORY / 'ccen-known-hosts'

PROBE = r'''
import concurrent.futures,json,pathlib,subprocess
def request(item):
    name,port,url=item
    args=['curl','-sS','--max-time','12','--proxy',f'http://127.0.0.1:{port}',url]
    if name=='codex':args[1:1]=['-o','/dev/null','-w','%{http_code}']
    r=subprocess.run(args,capture_output=True,text=True)
    if r.returncode:return name,{'ok':False,'reason':'代理请求未成功'}
    if name=='codex':return name,{'ok':r.stdout.strip()=='200','code':r.stdout.strip()}
    trace=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
    return name,{'ok':True,'ip':trace.get('ip',''),'country':trace.get('loc',''),'colo':trace.get('colo','')}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    result=dict(pool.map(request,[('claude',17899,'https://claude.ai/cdn-cgi/trace'),('codex',7897,'https://auth.openai.com/.well-known/openid-configuration')]))
print(json.dumps(result))
'''


def execute(args, timeout=25, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'SSH 操作未完成')
    return result


class RemoteConnection:
    def __init__(self, log, prompt):
        self.log = log
        self.prompt = prompt
        self.lock = threading.Lock()
        self.config = json.loads(TARGET.read_text()) if TARGET.exists() else None
        self.state = dict(connected=False, phase='checking', message='正在检查服务器',
                          claude=dict(ok=False), codex=dict(ok=False), checked_at='')
        self.last_check = 0

    def snapshot(self):
        return dict(self.state, configured=self.config is not None,
                    gateway=self.config['gateway'] if self.config else {},
                    folder=self.config['shared_home'] if self.config else '',
                    node=self.config.get('last_node', '') if self.config else '')

    def control(self, action):
        endpoint = self.config['gateway']
        return subprocess.run([SSH, '-S', str(CONTROL), '-O', action, '-p', str(endpoint['port']),
                               endpoint['user']+'@'+endpoint['host']], capture_output=True, text=True, timeout=8)

    def check(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            self._check()
        finally:
            self.last_check = time.monotonic()
            self.lock.release()

    def _check(self):
        old = self.state['connected']
        if self.config is None or self.control('check').returncode:
            if self.state['phase'] == 'connection_failed':
                return
            self.state = dict(connected=False, phase='needs_connection', message='点击“连接服务器”，在弹窗输入当次密码。',
                              claude=dict(ok=False), codex=dict(ok=False), checked_at=time.strftime('%H:%M:%S'))
        else:
            try:
                result = execute([SSH, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', 'ccen',
                                  'python3 -c '+shlex.quote(PROBE)])
                links = json.loads(result.stdout)
                c = links['claude']
                c['ok'] = bool(c['ok'] and (c.get('ip'), c.get('country'), c.get('colo')) ==
                               (EXPECTED_IP, EXPECTED_COUNTRY, EXPECTED_COLO))
                self.state = dict(connected=True, phase='connected', message='服务器已连接，桌面应用可使用 ccen。',
                                  **links, checked_at=time.strftime('%H:%M:%S'))
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                self.state = dict(connected=False, phase='connection_failed', message=str(error),
                                  claude=dict(ok=False), codex=dict(ok=False), checked_at=time.strftime('%H:%M:%S'))
        if old != self.state['connected']:
            self.log('服务器连接已恢复。' if self.state['connected'] else '服务器连接已中断，请点击连接服务器。')

    def connect(self, host=None, user=None, port=None):
        if self.config is None:
            return dict(ok=False, error='尚未完成这台 Mac 的 SSH 密钥和共享目录配置。')
        endpoint = dict(self.config['gateway']) if host is None else dict(host=host.strip(), user=user.strip(), port=int(port))
        if not re.fullmatch(r'[A-Za-z0-9_.:-]+', endpoint['host']) or endpoint['host'].startswith('-'):
            return dict(ok=False, error='服务器地址格式不正确。')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', endpoint['user']) or not 1 <= endpoint['port'] <= 65535:
            return dict(ok=False, error='用户名或端口格式不正确。')
        with self.lock:
            previous = dict(self.state)
            password = None
            try:
                active = self.control('check').returncode == 0
                # Explicit node replacement must reconnect even when the gateway
                # address and username were reused by a new allocation.
                if active and host is None:
                    self._check()
                    if self.state['connected']:
                        return dict(ok=True)
                self.state.update(phase='awaiting_password', message='请在密码窗口粘贴当次密码，确认后开始连接。')
                password = self.prompt(
                    f"{endpoint['user']}@{endpoint['host']}:{endpoint['port']}\n"
                    '支持 ⌘V 粘贴、⌘A 全选。点击“连接”后才开始登录；密码不会保存。',
                    password=True)
                if password is None:
                    self.state = previous
                    return dict(ok=True)
                if not password:
                    raise RuntimeError('密码不能为空，请重新输入。')
                if '\n' in password or '\r' in password:
                    raise RuntimeError('密码中含有换行，请只复制密码这一行后重试。')
                self.state.update(phase='connecting', connected=False,
                                  message='正在登录新节点并建立通道…',
                                  claude=dict(ok=False), codex=dict(ok=False))
                self.log(f"开始连接 {endpoint['user']}@{endpoint['host']}:{endpoint['port']}。")
                if active:
                    result = self.control('exit')
                    if result.returncode:
                        raise RuntimeError('旧服务器未能断开。')
                self._start(endpoint, password)
                password = None
                self.state.update(message='已完成节点切换，正在核验远端出口…')
                self._check()
                if not self.state['connected']:
                    raise RuntimeError(self.state['message'])
                self.log('服务器已接入桌面应用，代理状态将持续更新。')
                return dict(ok=True)
            except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as error:
                self.state.update(phase='connection_failed', connected=False, message=str(error))
                self.log('连接失败：'+str(error))
                return dict(ok=False, error=str(error))
            finally:
                password = None
                self.last_check = time.monotonic()

    def _start(self, endpoint, password):
        identity = str(Path(self.config['identity']).expanduser())
        destination = endpoint['user']+'@'+endpoint['host']
        args = [SSH, '-fNT', '-M', '-S', str(CONTROL), '-p', str(endpoint['port']), '-i', identity,
                '-o', 'IdentitiesOnly=yes', '-o', 'ControlPersist=no', '-o', 'ExitOnForwardFailure=yes',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', '-o', 'ConnectTimeout=10',
                '-o', 'NumberOfPasswordPrompts=1', '-L', '127.0.0.1:22030:127.0.0.1:22',
                '-R', '127.0.0.1:17899:127.0.0.1:17899',
                '-R', f'127.0.0.1:7897:127.0.0.1:{ORDINARY_PORT}', destination]
        try:
            login(args, password, self.prompt)
        finally:
            password = None
        self.log('SSH 登录成功，已建立 CCEN 通道。')
        try:
            probe = "import os,pwd,socket,json,pathlib; print(json.dumps(dict(user=pwd.getpwuid(os.getuid()).pw_name,home=str(pathlib.Path.home().resolve()),host=socket.gethostname(),key=pathlib.Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip())))"
            remote = json.loads(execute([SSH, '-S', str(CONTROL), '-p', str(endpoint['port']), destination,
                                        'python3 -c '+shlex.quote(probe)]).stdout)
            if remote['user'] != self.config['inner_user'] or remote['home'] != self.config['shared_home']:
                raise RuntimeError('新节点的用户或共享目录不同，不能沿用当前应用配置。')
            host_alias = 'ccen-'+remote['host']
            line = host_alias+' '+' '.join(remote['key'].split()[:2])+'\n'
            existing = KNOWN_HOSTS.read_text() if KNOWN_HOSTS.exists() else ''
            if line not in existing:
                KNOWN_HOSTS.write_text(existing+line)
                KNOWN_HOSTS.chmod(0o600)
            execute([SSH, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                     '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
                     '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                     '-o', 'HostKeyAlias='+host_alias, '-o', 'UserKnownHostsFile='+str(KNOWN_HOSTS),
                     '-p', '22030', '-i', identity, remote['user']+'@127.0.0.1',
                     'command -v codex >/dev/null && command -v claude >/dev/null'])
            CONFIG.write_text(f'''# Managed by CCEN.
Host ccen
    HostName 127.0.0.1
    Port 22030
    User {remote['user']}
    IdentityFile "{identity}"
    IdentitiesOnly yes
    HostKeyAlias {host_alias}
    UserKnownHostsFile "{KNOWN_HOSTS}"
    StrictHostKeyChecking yes
    ControlMaster no
    ControlPath none
    ServerAliveInterval 15
    ServerAliveCountMax 3
''')
            CONFIG.chmod(0o600)
            self.config.update(gateway=endpoint, last_node=remote['host'])
            TARGET.write_text(json.dumps(self.config, ensure_ascii=False, indent=2)+'\n')
            TARGET.chmod(0o600)
            self.log('已确认原共享目录及工具，ccen 已切换到节点 '+remote['host']+'。')
        except Exception:
            execute([SSH, '-S', str(CONTROL), '-O', 'exit', '-p', str(endpoint['port']), destination])
            raise

    def disconnect(self):
        with self.lock:
            if self.config and self.control('check').returncode == 0:
                result = self.control('exit')
                if result.returncode:
                    return dict(ok=False, error=result.stderr.strip())
            self.state.update(connected=False, phase='needs_connection', message='已断开服务器连接。',
                              claude=dict(ok=False), codex=dict(ok=False))
            self.log('已断开 CCEN 的服务器连接。')
        return dict(ok=True)
