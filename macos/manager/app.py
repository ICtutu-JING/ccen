from __future__ import annotations

import fcntl
import os
import shutil
import sys
import threading
import traceback
from pathlib import Path

import AppKit
import Foundation
import objc
import webview
from PyObjCTools import AppHelper

NAME = 'Claude / Codex 连接管理器'
ACTIVATE = 'com.ccen.connection-manager.activate'
ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DATA = Path(os.environ.get('CCEN_DATA_DIR', Path.home() / 'Library/Application Support/ClaudeConnectionManager'))


def alert(title, message):
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    dialog = AppKit.NSAlert.alloc().init()
    dialog.setMessageText_(title)
    dialog.setInformativeText_(message)
    dialog.runModal()


class MenuController(Foundation.NSObject):
    def show_(self, sender):
        self.owner.show()

    def check_(self, sender):
        self.owner.manager.check_now()

    def quit_(self, sender):
        self.owner.quit()

    def activate_(self, notification):
        self.owner.show()

    def applicationShouldTerminate_(self, sender):
        self.owner.quit()
        return AppKit.NSTerminateCancel

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, visible):
        self.owner.show()
        return True

    def applicationSupportsSecureRestorableState_(self, sender):
        return True


class App:
    def __init__(self, manager):
        self.manager = manager
        self.exiting = False
        self.quitting = False
        self.controller = MenuController.alloc().init()
        self.controller.owner = self
        self.status_item = None
        html = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        html = html.replace('/* APP_STYLE */', (ROOT / 'ui/style.css').read_text(encoding='utf-8'))
        html = html.replace('// APP_SCRIPT', (ROOT / 'ui/app.js').read_text(encoding='utf-8'))
        self.window = webview.create_window(NAME, html=html, width=1170, height=840,
            min_size=(960, 720), background_color='#f4f6f3', hidden='--tray' in sys.argv)
        self.window.expose(self.manager.snapshot, self.manager.set_guard, self.manager.check_now,
            self.manager.set_startup, self.manager.connect_server, self.manager.disconnect_server,
            self.manager.open_client, self.manager.open_logs)
        self.window.events.closing += self.on_close
        self.window.events.loaded += self.on_loaded

    def show(self):
        self.window.show()
        self.window.restore()
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def on_close(self):
        if self.exiting:
            return True
        self.window.hide()
        return False

    def on_loaded(self):
        AppHelper.callAfter(self.install_menu)

    def install_menu(self):
        if self.status_item is not None:
            return
        app = AppKit.NSApplication.sharedApplication()
        app.setDelegate_(self.controller)
        self.status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        icon = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_('checkmark.shield', NAME)
        icon.setTemplate_(True)
        self.status_item.button().setImage_(icon)
        self.status_item.button().setToolTip_(NAME)
        menu = AppKit.NSMenu.alloc().initWithTitle_(NAME)
        for title, action in [('打开管理器', 'show:'), ('检查链路', 'check:'),
                              ('退出并停止本应用托管服务', 'quit:')]:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
            item.setTarget_(self.controller)
            menu.addItem_(item)
        self.status_item.setMenu_(menu)
        Foundation.NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.controller, 'activate:', ACTIVATE, str(DATA))

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        threading.Thread(target=self.stop_services, daemon=True).start()

    def stop_services(self):
        try:
            self.manager.stop()
        except Exception as error:
            self.quitting = False
            AppHelper.callAfter(alert, '停止服务失败', str(error))
            return
        AppHelper.callAfter(self.finish_quit)

    def finish_quit(self):
        self.exiting = True
        Foundation.NSDistributedNotificationCenter.defaultCenter().removeObserver_(self.controller)
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
        self.window.destroy()

    def run(self):
        self.manager.start()
        webview.start(gui='cocoa', debug=False, private_mode=True)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / 'manager.lock').open('a') as instance:
        try:
            fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            Foundation.NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_(ACTIVATE, str(DATA))
            return
        config = DATA / 'deployment.json'
        if not config.exists():
            shutil.copyfile(ROOT / 'deployment.example.json', config)
            alert(NAME + '：首次配置',
                '请填写 deployment.json 中的本机住宅代理端口、固定出口 IP、国家和节点，保存后重新打开应用。仅在启用远端时填写 SSH 别名和远端目录。\n\n' + str(config))
            import subprocess
            subprocess.run(['/usr/bin/open', '-a', 'TextEdit', str(config)], check=True)
            return
        from core import Manager
        App(Manager(native_prompt)).run()


def native_prompt(message, password=False):
    """Show the dialog on the existing app's main thread before starting SSH."""
    done = threading.Event()
    answer = {}

    def show():
        field = None
        try:
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            dialog = AppKit.NSAlert.alloc().init()
            dialog.setMessageText_('CCEN · 连接服务器' if password else 'CCEN · 确认服务器身份')
            dialog.setInformativeText_(message)
            dialog.addButtonWithTitle_('连接' if password else '信任并继续')
            dialog.addButtonWithTitle_('取消')
            if password:
                field = AppKit.NSSecureTextField.alloc().initWithFrame_(((0, 0), (380, 28)))
                field.setPlaceholderString_('在此粘贴当次密码（⌘V），不保存')
                dialog.setAccessoryView_(field)
                dialog.window().setInitialFirstResponder_(field)
            accepted = dialog.runModal() == AppKit.NSAlertFirstButtonReturn
            answer['value'] = (str(field.stringValue()) if password else True) if accepted else None
        except Exception as error:
            answer['error'] = error
        finally:
            if field is not None:
                field.setStringValue_('')
            done.set()

    AppHelper.callAfter(show)
    done.wait()
    if 'error' in answer:
        raise answer['error']
    return answer['value']


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        traceback.print_exc()
        alert(NAME + '：启动失败', str(error))
        sys.exit(1)
