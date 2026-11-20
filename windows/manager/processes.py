"""Keep existing managed connections alive across an application update."""
import ctypes
import subprocess
from ctypes import wintypes


kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]


class AttachedProcess:
    def __init__(self, pid):
        self.pid = pid
        self.handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = None

    def poll(self):
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = None if code.value == 259 else code.value
        return self.returncode

    def wait(self, timeout):
        result = kernel.WaitForSingleObject(self.handle, int(timeout * 1000))
        if result == 258:
            raise subprocess.TimeoutExpired(str(self.pid), timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def __del__(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
