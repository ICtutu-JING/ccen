"""Discover and control the current user's dedicated macOS processes."""
import os

import psutil


class AttachedProcess:
    def __init__(self, pid):
        self.process = psutil.Process(pid)
        self.pid = pid
        self.returncode = None

    def poll(self):
        if not self.process.is_running() or self.process.status() == psutil.STATUS_ZOMBIE:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.process.terminate()

    def wait(self, timeout):
        self.returncode = self.process.wait(timeout=timeout)
        return self.returncode


def guard_processes(data):
    found = []
    guard = str(data / 'guard/guard.cjs')
    for process in psutil.process_iter(['pid', 'uids', 'name', 'cmdline']):
        row = process.info
        if row['uids'] is None or row['uids'].real != os.getuid():
            continue
        args = row['cmdline'] or []
        if row['name'] == 'node' and len(args) == 2 and args[1] == guard:
            found.append(row['pid'])
    return found
