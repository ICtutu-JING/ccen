from __future__ import annotations

import ctypes
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog

import pystray
import webview
from PIL import Image, ImageDraw


NAME = 'Claude / Codex 连接管理器'
HANDLES = []


def single_instance():
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateEventW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, 'Local\\ClaudeConnectionManager.Mutex')
    exists = kernel.GetLastError() == 183
    event = kernel.CreateEventW(None, False, False, 'Local\\ClaudeConnectionManager.Activate')
    HANDLES.extend([mutex, event])
    if exists:
        kernel.SetEvent(ctypes.c_void_p(event))
        return False
    return True


def icon_image():
    im = Image.new('RGBA', (64, 64), '#102421')
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((5, 5, 59, 59), radius=17, fill='#183c34')
    d.line([(18, 34), (27, 43), (46, 23)], fill='#b5f3cb', width=6)
    return im


def server_prompt(message, password=False):
    parent = tk.Tk()
    parent.withdraw()
    parent.attributes('-topmost', True)
    try:
        if password:
            return simpledialog.askstring(
                'CCEN · 连接服务器',
                message + '\n请用 Ctrl+V 粘贴当次 SSH 密码。密码不会保存。',
                show='*', parent=parent,
            )
        return messagebox.askyesno('CCEN · 核对网关主机指纹', message, parent=parent)
    finally:
        parent.destroy()


class App:
    def __init__(self):
        self.manager = Manager(server_prompt)
        self.exiting = False
        self.tray = None
        html = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        html = html.replace('/* APP_STYLE */', (ROOT / 'ui/style.css').read_text(encoding='utf-8'))
        html = html.replace('// APP_SCRIPT', (ROOT / 'ui/app.js').read_text(encoding='utf-8'))
        self.window = webview.create_window(NAME, html=html, width=1170, height=840,
                    min_size=(960, 720), background_color='#f4f6f3', hidden='--tray' in sys.argv)
        self.window.expose(self.manager.snapshot, self.manager.set_guard, self.manager.set_reconnect,
                           self.manager.set_codex_reconnect,
                           self.manager.connect_server, self.manager.disconnect_server,
                           self.manager.check_now, self.manager.restart_owned_tunnel,
                           self.manager.set_startup, self.manager.open_vscode, self.manager.open_logs)
        self.window.events.closing += self.on_close
        self.window.events.loaded += self.on_loaded

    def show(self):
        self.window.show()
        self.window.restore()

    def on_close(self):
        if self.exiting:
            return True
        self.window.hide()
        return False

    def on_loaded(self):
        if self.tray is not None:
            return
        self.tray = pystray.Icon('ClaudeConnectionManager', icon_image(), NAME, menu=pystray.Menu(
            pystray.MenuItem('打开管理器', self.show, default=True),
            pystray.MenuItem('检查链路', lambda: self.manager.check_now()),
            pystray.MenuItem('退出并停止本应用托管服务', self.quit)))
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.manager.start()
        threading.Thread(target=self.activate_loop, daemon=True).start()

    def activate_loop(self):
        while not self.exiting:
            if ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(HANDLES[1]), 1000) == 0:
                self.show()

    def quit(self):
        self.exiting = True
        self.manager.stop()
        self.tray.stop()
        self.window.destroy()

    def run(self):
        webview.start(gui='edgechromium', debug=False, private_mode=True)


if __name__ == '__main__':
    try:
        from core import Manager, ROOT
        if single_instance():
            App().run()
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), NAME + '：启动失败', 0x10)
