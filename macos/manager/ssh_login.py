"""Authenticate OpenSSH using a private PTY, without recording its input."""
import os

import pexpect


def login(args, password, confirm_host):
    env = dict(os.environ, SSH_ASKPASS_REQUIRE='never', LC_ALL='C')
    child = pexpect.spawn(args[0], args[1:], env=env, encoding='utf-8',
                          echo=False, timeout=30)
    try:
        while True:
            result = child.expect([
                r'(?i)password:\s*$',
                r'Are you sure you want to continue connecting \(yes/no(?:/\[fingerprint\])?\)\?',
                pexpect.EOF, pexpect.TIMEOUT,
            ])
            if result == 0:
                if password is None:
                    raise RuntimeError('服务器未接受密码，请检查当次密码后重试。')
                child.sendline(password)
                password = None
            elif result == 1:
                if not confirm_host(child.before + child.after):
                    raise RuntimeError('已取消服务器身份确认。')
                child.sendline('yes')
            elif result == 2:
                detail = child.before.strip()
                child.close()
                if child.exitstatus != 0:
                    raise RuntimeError('SSH 登录或转发失败：' + (detail or '服务器关闭了连接。'))
                return
            else:
                raise RuntimeError('SSH 登录超时，请检查节点是否在线后重试。')
    finally:
        password = None
        child.close()
