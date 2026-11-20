"""Smoke-check password delivery through real Windows OpenSSH in the release job."""
import json
import os
import socket
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import paramiko

from ssh_login import login


TEST_PASSWORD = 'CCEN-local-test-only'
IDENTITY = {'user': 'fixture', 'home': '/home/fixture', 'host': 'fixture'}


class LocalServer(paramiko.ServerInterface):
    def __init__(self):
        self.command = threading.Event()
        self.password_received = False

    def get_allowed_auths(self, username):
        return 'password'

    def check_auth_password(self, username, password):
        self.password_received = (username, password) == ('fixture', TEST_PASSWORD)
        return paramiko.AUTH_SUCCESSFUL if self.password_received else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.command.set()
        return True


def main():
    ssh = Path(os.environ['WINDIR']) / 'System32/OpenSSH/ssh.exe'
    key = paramiko.RSAKey.generate(2048)
    server = LocalServer()
    with TemporaryDirectory(prefix='ccen-') as directory, socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(20)
        port = listener.getsockname()[1]
        known_hosts = Path(directory) / 'known_hosts'
        known_hosts.write_text(f'[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n', encoding='ascii')
        done = threading.Event()

        def serve():
            sock, _ = listener.accept()
            with paramiko.Transport(sock) as transport:
                transport.add_server_key(key)
                transport.start_server(server=server)
                channel = transport.accept(15)
                if channel is None or not server.command.wait(15):
                    raise RuntimeError('OpenSSH did not start the test session')
                channel.sendall('CCEN_IDENTITY ' + json.dumps(IDENTITY) + '\n')
                done.wait(30)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        args = [
            str(ssh), '-F', 'none', '-T',
            '-o', 'PreferredAuthentications=password', '-o', 'NumberOfPasswordPrompts=1',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile="{known_hosts.as_posix()}"',
            '-p', str(port), 'fixture@127.0.0.1', 'ccen-fixture',
        ]

        def reject_unknown_host(_):
            raise AssertionError('The fixture must use its known host key')

        child, remote = login(args, TEST_PASSWORD, reject_unknown_host)
        try:
            assert remote == IDENTITY and server.password_received and child.isalive()
            print('Windows OpenSSH accepted the password via ConPTY and returned the node identity.')
        finally:
            done.set()
            child.close(force=True)
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
