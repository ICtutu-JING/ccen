"""The password-based SSH gateway selected from the Windows server card."""
import json
import re
import shlex
from pathlib import Path

from ssh_login import login


ALIAS = 'ccen'
LOCAL_SSH_PORT = 22030
FORWARDS = (17899, 7899, 7897)
IDENTITY_COMMAND = r'''
import json, os, pathlib, pwd, socket, sys
print('CCEN_IDENTITY ' + json.dumps(dict(
    user=pwd.getpwuid(os.getuid()).pw_name,
    home=str(pathlib.Path.home().resolve()),
    host=socket.gethostname(),
    key=pathlib.Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip(),
)), flush=True)
sys.stdin.buffer.read()
'''
PROBE = r'''
import concurrent.futures, json, subprocess
def check(item):
    name, port, url = item
    args = ['curl','--disable','-sS','--max-time','10','--noproxy','',
            '--proxy',f'http://127.0.0.1:{port}',url]
    if name == 'codex':
        args.extend(['--output','/dev/null','--write-out','%{http_code}'])
    result = subprocess.run(args, capture_output=True, text=True)
    return name, dict(ok=result.returncode == 0, output=result.stdout.strip())
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    print(json.dumps(dict(pool.map(check, [
        ('claude',17899,'https://claude.ai/cdn-cgi/trace'),
        ('codex',7897,'https://auth.openai.com/.well-known/openid-configuration'),
    ]))))
'''


def endpoint(host, user, port):
    host, user = host.strip(), user.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.:][A-Za-z0-9_.:-]*', host):
        raise ValueError('服务器地址格式不正确。')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', user):
        raise ValueError('平台登录用户名格式不正确。')
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError('SSH 端口必须是 1 到 65535 之间的整数。')
    return dict(host=host, user=user, port=int(port))


class Gateway:
    def __init__(self, ssh, prompt, run, directory=None):
        self.ssh = str(ssh)
        self.prompt = prompt
        self.run = run
        self.directory = Path.home() / '.ssh' if directory is None else Path(directory)
        self.target = self.directory / 'ccen-target.json'
        self.alias_file = self.directory / 'ccen.conf'
        self.known_hosts = self.directory / 'ccen-known-hosts'
        self.config = json.loads(self.target.read_text(encoding='utf-8')) if self.target.exists() else None
        self.child = None
        self.phase = 'idle'
        self.message = ''
        self.connections = 0

    @property
    def connected(self):
        return self.child is not None and self.child.isalive()

    def snapshot(self):
        config = self.config or {}
        return dict(configured=bool(config), gateway=config.get('gateway', {}),
                    node=config.get('last_node', ''), account={
                        key: config.get(key, '') for key in ('inner_user', 'shared_home', 'identity')
                    }, connected=self.connected, phase=self.phase, message=self.message)

    def _save(self, config):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.target.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        self.config = config

    def _add_account(self, gateway, account):
        if self.config and self.config.get('last_node'):
            raise ValueError('已配置 Linux 账户，请使用“更换节点”。')
        user = account['inner_user'].strip()
        home = account['shared_home'].strip()
        key = Path(account['identity'].strip()).expanduser()
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', user):
            raise ValueError('实际 Linux 用户名格式不正确。')
        if not home.startswith('/') or '\n' in home or '\r' in home:
            raise ValueError('请填写远端家目录的绝对路径。')
        if not key.is_absolute() or not key.is_file() or key.suffix.lower() == '.pub':
            raise ValueError('找不到 SSH 私钥，请填写已授权公钥对应的本机私钥路径。')
        return dict(gateway=gateway, inner_user=user, shared_home=home, identity=key.as_posix())

    def _write_alias(self, config, remote):
        identity = Path(config['identity']).expanduser().as_posix()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', remote['host']):
            raise ValueError('远端主机名格式不正确。')
        alias = 'ccen-' + remote['host']
        key_type, public_key, *_ = remote['key'].split()
        if key_type != 'ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+', public_key):
            raise ValueError('远端没有可用的 ED25519 主机公钥。')

        record = f'{alias} {key_type} {public_key}'
        existing = self.known_hosts.read_text(encoding='utf-8') if self.known_hosts.exists() else ''
        if record not in existing.splitlines():
            with self.known_hosts.open('a', encoding='utf-8') as stream:
                stream.write(record + '\n')

        proxy = self.run([
            self.ssh, '-F', 'none', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentitiesOnly=yes',
            '-o', f'HostKeyAlias={alias}', '-o', f'UserKnownHostsFile="{self.known_hosts.as_posix()}"',
            '-i', identity, '-p', str(LOCAL_SSH_PORT), config['inner_user'] + '@127.0.0.1',
            'command -v codex >/dev/null && command -v claude >/dev/null',
        ], timeout=15)
        if proxy.returncode:
            if 'Permission denied' in proxy.stderr:
                raise RuntimeError('无法用本机公钥登录实际 Linux 用户，请检查 authorized_keys 和私钥。')
            if 'Host key verification failed' in proxy.stderr:
                raise RuntimeError('内部 SSH 主机密钥核验失败，请核对实际节点。')
            raise RuntimeError('内部 SSH 或远端工具未就绪。请确认目标监听 22 端口，登录 shell 可以运行 codex 和 claude。')

        self.alias_file.write_text(f'''# Managed by CCEN.
Host {ALIAS}
    HostName 127.0.0.1
    Port {LOCAL_SSH_PORT}
    User {config['inner_user']}
    IdentityFile "{identity}"
    IdentitiesOnly yes
    HostKeyAlias {alias}
    UserKnownHostsFile "{self.known_hosts.as_posix()}"
    StrictHostKeyChecking yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
''', encoding='utf-8')
        config_file = self.directory / 'config'
        existing = config_file.read_bytes() if config_file.exists() else b''
        global_config = re.split(rb'(?im)^\s*(?:host|match)\s+', existing, maxsplit=1)[0]
        include = b'Include ~/.ssh/ccen.conf'
        if include not in (line.strip() for line in global_config.splitlines()):
            config_file.write_bytes(include + b'\n' + existing)

    def connect(self, prepare, host=None, user=None, port=None, account=None):
        if self.config is None and account is None:
            raise ValueError('请先添加服务器。')
        gateway = endpoint(host, user, port) if host is not None else self.config['gateway']
        config = self._add_account(gateway, account) if account is not None else self.config
        self.phase = 'password'
        try:
            password = self.prompt(f"{gateway['user']}@{gateway['host']}:{gateway['port']}", password=True)
            if password is None:
                return
            if not password or any(character in password for character in '\r\n'):
                raise ValueError('请只粘贴当次 SSH 密码这一行。')
            self.phase = 'connecting'
            self.close()
            prepare()
            if account is not None:
                self._save(config)

            forwards = [option for port in FORWARDS
                        for option in ('-R', f'127.0.0.1:{port}:127.0.0.1:{port}')]
            args = [
                self.ssh, '-T', '-o', 'BatchMode=no', '-o', 'StrictHostKeyChecking=ask',
                '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                '-o', 'NumberOfPasswordPrompts=1', '-p', str(gateway['port']),
                '-L', f'127.0.0.1:{LOCAL_SSH_PORT}:127.0.0.1:22', *forwards,
                gateway['user'] + '@' + gateway['host'],
                'python3 -c ' + shlex.quote(IDENTITY_COMMAND),
            ]
            child, remote = login(args, password, self.prompt)
            try:
                if (remote['user'], remote['home']) != (config['inner_user'], config['shared_home']):
                    raise RuntimeError('目标的实际 Linux 用户或家目录不同，请核对服务器信息。')
                self._write_alias(config, remote)
                self._save(dict(config, gateway=gateway, last_node=remote['host']))
            except Exception:
                child.close(force=True)
                raise
            self.child = child
            self.connections += 1
            self.message = '服务器已连接，桌面应用可使用 ccen。'
        finally:
            self.phase = 'idle'

    def probe(self, expected):
        if not self.connected:
            return dict(reachable=False, verified=False, ports=[],
                        reason=self.message or '点击“连接服务器”，粘贴当次密码。')
        result = self.run([
            self.ssh, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            ALIAS, 'python3 -c ' + shlex.quote(PROBE),
        ], timeout=20)
        if result.returncode:
            return dict(reachable=False, verified=False, ports=[],
                        reason='内部 SSH 或远端连通性检查失败。')
        output = json.loads(result.stdout)
        claude, codex = output['claude'], output['codex']
        trace = dict(line.split('=', 1) for line in claude['output'].splitlines() if '=' in line)
        fields = tuple(trace.get(key, '—') for key in ('ip', 'loc', 'colo'))
        verified = claude['ok'] and fields == expected
        codex_ok = codex['ok'] and codex['output'] == '200'
        return dict(reachable=True, verified=verified, ports=list(FORWARDS),
                    ip=fields[0], region=fields[1], colo=fields[2],
                    reason='固定住宅出口核验通过。' if verified else '远端住宅出口尚未通过核验，请检查本机守卫。',
                    codex=dict(verified=codex_ok, reason='Codex 授权服务可达。' if codex_ok else '远端普通代理未通过核验。'))

    def close(self):
        if self.child is not None:
            self.child.close(force=True)
            self.child = None
        self.message = ''
