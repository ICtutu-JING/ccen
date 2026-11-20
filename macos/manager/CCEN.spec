import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH)
node = Path(os.environ['CCEN_NODE']).resolve()
data = [(str(root / name), name) for name in ('ui', 'resources')]
data += [(str(root / 'deployment.example.json'), '.')]
data += collect_data_files('webview')
for package in ('pywebview', 'Pillow', 'psutil', 'pexpect', 'ptyprocess', 'pyobjc-core', 'pyobjc-framework-Cocoa',
                'pyobjc-framework-Quartz', 'pyobjc-framework-WebKit', 'pyobjc-framework-Security'):
    data += copy_metadata(package)

analysis = Analysis([str(root / 'app.py')], pathex=[str(root)],
    binaries=[(str(node), 'runtime')], datas=data,
    hiddenimports=['webview.platforms.cocoa'], excludes=['tkinter'])
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
    name='ClaudeConnectionManager', console=False, target_arch=None,
    icon=str(root / 'resources/app.icns'))
collection = COLLECT(executable, analysis.binaries, analysis.datas,
    name='ClaudeConnectionManager')
application = BUNDLE(collection, name='ClaudeConnectionManager.app',
    icon=str(root / 'resources/app.icns'), bundle_identifier='com.ccen.connection-manager',
    info_plist={'CFBundleDisplayName': 'Claude / Codex 连接管理器',
                'CFBundleShortVersionString': '2026.11.20',
                'LSMinimumSystemVersion': '13.5', 'NSHighResolutionCapable': True})
