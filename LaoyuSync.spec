# PyInstaller native platform build. macOS and Windows are built independently.
import sys
import os
from pathlib import Path
root = Path(SPECPATH)
datas = [(str(root/'ui'), 'ui'), (str(root/'engine'), 'engine'), (str(root/'assets'), 'assets'), (str(root/'licenses'), 'licenses'), (str(root/'THIRD_PARTY_NOTICES.md'), '.')]
if os.environ.get('LAOYU_FEEDBACK_CONFIG_PATH'):
    feedback_config = Path(os.environ['LAOYU_FEEDBACK_CONFIG_PATH']).resolve()
    if feedback_config.name != 'feedback-channel.json' or not feedback_config.is_file():
        raise ValueError('Feedback build configuration must be feedback-channel.json')
    datas.append((str(feedback_config), '.'))
a = Analysis([str(root/'core/app.py')], pathex=[str(root/'core')], binaries=[], datas=datas,
             hiddenimports=['webview', 'qrcode.image.svg', 'tkinter', 'pet'] + (['webview.platforms.edgechromium'] if sys.platform == 'win32' else ['webview.platforms.cocoa']),
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['matplotlib','numpy','pandas','scipy','IPython','pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='LaoyuSync', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root/'assets/app.ico') if sys.platform=='win32' else str(root/'assets/app.icns'), version=str(root/'assets/version_info.txt') if sys.platform=='win32' else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LaoyuSync')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='LaoyuSync.app', icon=str(root/'assets/app.icns'), bundle_identifier='studio.laoyu.sync',
                 info_plist={'CFBundleShortVersionString':'0.3.3','NSHighResolutionCapable':True})
