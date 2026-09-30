# PyInstaller native platform build. macOS and Windows are built independently.
import sys
from pathlib import Path
root = Path(SPECPATH)
datas = [(str(root/'ui'), 'ui'), (str(root/'engine'), 'engine'), (str(root/'assets'), 'assets'), (str(root/'THIRD_PARTY_NOTICES.md'), '.')]
a = Analysis([str(root/'core/app.py')], pathex=[str(root/'core')], binaries=[], datas=datas,
             hiddenimports=['webview', 'qrcode.image.svg', 'tkinter', 'pet'] + (['webview.platforms.edgechromium'] if sys.platform == 'win32' else ['webview.platforms.cocoa']),
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['matplotlib','numpy','pandas','scipy','IPython','pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LaoyuSync', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root/'assets/app.ico') if sys.platform=='win32' else str(root/'assets/app.icns'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LaoyuSync')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='LaoyuSync.app', icon=str(root/'assets/app.icns'), bundle_identifier='studio.laoyu.sync',
                 info_plist={'CFBundleShortVersionString':'0.3.0','NSHighResolutionCapable':True})
