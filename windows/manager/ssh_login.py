"""Pass a temporary password to Windows OpenSSH through a private console."""
import json
import os
import queue
import re
import threading

from winpty import PtyProcess


ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')
PASSWORD = re.compile(r'password:\s*$', re.I)
HOST_CONFIRMATION = re.compile(r'Are you sure you want to continue connecting \(yes/no(?:/\[fingerprint\])?\)\?')


def login(args, password, confirm_host):
    env = dict(os.environ, LC_ALL='C', SSH_ASKPASS_REQUIRE='never')
    child = PtyProcess.spawn(args, env=env, dimensions=(30, 512))
    messages = queue.Queue()
    running = threading.Event()

    def drain_output():
        try:
            while True:
                chunk = child.read(4096)
                if not running.is_set():
                    messages.put(chunk)
        except (EOFError, OSError):
            if not running.is_set():
                messages.put(None)

    threading.Thread(target=drain_output, daemon=True).start()
    pending = ''
    try:
        while True:
            try:
                chunk = messages.get(timeout=30)
            except queue.Empty:
                raise RuntimeError('SSH 登录超时，请检查网络和平台入口。') from None
            if chunk is None:
                raise RuntimeError('SSH 登录失败。请检查当次密码、服务器状态，以及远端转发端口是否已被占用。')
            pending = (pending + chunk)[-8192:]
            output = ANSI.sub('', pending)
            identity = re.search(r'(?:^|[\r\n])CCEN_IDENTITY (\{[^\r\n]+\})', output)
            if identity:
                result = json.loads(identity[1])
                running.set()
                return child, result
            if HOST_CONFIRMATION.search(output):
                if not confirm_host(output.strip()):
                    raise RuntimeError('已取消服务器身份确认。')
                child.write('yes\r')
                pending = ''
            elif PASSWORD.search(output):
                if password is None:
                    raise RuntimeError('服务器未接受密码，请检查当次密码后重试。')
                child.write(password + '\r')
                password = None
                pending = ''
            elif 'REMOTE HOST IDENTIFICATION HAS CHANGED' in output:
                raise RuntimeError('网关主机密钥发生变化，请通过可信渠道核对。')
            elif 'remote port forwarding failed' in output or 'Address already in use' in output:
                raise RuntimeError('SSH 转发端口被占用，请检查旧连接后重试。')
    finally:
        if not running.is_set():
            child.close(force=True)
