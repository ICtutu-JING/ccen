#!/usr/bin/env python3
"""PID 1 for Claude's private network namespace.

The only TCP listener is a byte-transparent loopback proxy. Each connection is
relayed to the host IP gate through its mounted Unix-domain socket.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
from typing import Optional


# 17898 is the enforced Claude proxy. 7898 is also mirrored *inside the
# isolated namespace* so existing Claude tool commands that explicitly name
# the historical port keep working; both ports terminate at the same guarded
# Unix socket and cannot reach the host's 7898 directly.
LISTEN_ADDRESSES = (("127.0.0.1", 17898), ("127.0.0.1", 7898))
GATE_SOCKET = "/run/claude-ip-gate/proxy.sock"

_child: Optional[subprocess.Popen[bytes]] = None
_pending_signals: list[int] = []
_signal_lock = threading.RLock()
_stop = threading.Event()


def _forward_signal(signum: int, _frame: object) -> None:
    with _signal_lock:
        if _child is None:
            _pending_signals.append(signum)
            return
        if _child.poll() is None:
            try:
                _child.send_signal(signum)
            except ProcessLookupError:
                pass


def _pump(source: socket.socket, destination: socket.socket) -> None:
    try:
        while True:
            data = source.recv(64 * 1024)
            if not data:
                break
            destination.sendall(data)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _relay(client: socket.socket) -> None:
    upstream: Optional[socket.socket] = None
    try:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.connect(GATE_SOCKET)

        client_to_upstream = threading.Thread(
            target=_pump,
            args=(client, upstream),
            name="claude-gate-upload",
            daemon=True,
        )
        client_to_upstream.start()
        _pump(upstream, client)
        client_to_upstream.join(timeout=1.0)
    except OSError:
        # A closed or absent gate is the intended fail-closed state.
        pass
    finally:
        if upstream is not None:
            upstream.close()
        client.close()


def _accept_loop(listener: socket.socket) -> None:
    listener.settimeout(0.5)
    while not _stop.is_set():
        try:
            client, _address = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(
            target=_relay,
            args=(client,),
            name="claude-gate-connection",
            daemon=True,
        ).start()


def _install_signal_handlers() -> None:
    for name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM", "SIGUSR1", "SIGUSR2"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, _forward_signal)


def main() -> int:
    global _child

    if os.getpid() != 1:
        print("claude-net-pid1: must run as PID 1", file=sys.stderr)
        return 70
    if len(sys.argv) < 2 or not os.path.isabs(sys.argv[1]):
        print("claude-net-pid1: invalid Claude argument vector", file=sys.stderr)
        return 64

    _install_signal_handlers()

    listeners: list[socket.socket] = []
    try:
        for address in LISTEN_ADDRESSES:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(address)
            listener.listen(128)
            listeners.append(listener)
    except OSError as exc:
        for listener in listeners:
            listener.close()
        print(f"claude-net-pid1: cannot create private proxy: {exc}", file=sys.stderr)
        return 71

    for listener in listeners:
        threading.Thread(
            target=_accept_loop,
            args=(listener,),
            name=f"claude-gate-listener-{listener.getsockname()[1]}",
            daemon=True,
        ).start()

    try:
        child = subprocess.Popen(
            sys.argv[1:],
            stdin=None,
            stdout=None,
            stderr=None,
            close_fds=True,
        )
    except OSError as exc:
        for listener in listeners:
            listener.close()
        print(f"claude-net-pid1: cannot start Claude: {exc}", file=sys.stderr)
        return 72

    with _signal_lock:
        _child = child
        pending = tuple(_pending_signals)
        _pending_signals.clear()
    for signum in pending:
        if child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                break

    return_code = child.wait()
    _stop.set()
    for listener in listeners:
        listener.close()

    if return_code < 0:
        return 128 + (-return_code)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
