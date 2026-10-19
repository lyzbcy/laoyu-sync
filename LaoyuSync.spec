# PyInstaller native platform build. macOS and Windows are built independently.
import sys
import os
from pathlib import Path
root = Path(SPECPATH)
sys.path.insert(0, str(root/'core'))
from version import __version__
if sys.platform == 'darwin':
    import _tkinter
    if _tkinter.TK_VERSION != '8.6':
        raise RuntimeError('Mac desktop pet requires verified Tcl/Tk 8.6; Tk 9 renders an opaque background. See docs/packaging.md.')
datas = [(str(root/'ui'), 'ui'), (str(root/'assets'), 'assets'), (str(root/'licenses'), 'licenses'), (str(root/'THIRD_PARTY_NOTICES.md'), '.')]
for name in ['syncthing.exe' if sys.platform == 'win32' else 'syncthing', 'LICENSE.txt', 'AUTHORS.txt', 'UPSTREAM.txt']:
    datas.append((str(root/'engine'/name), 'engine'))
feedback_config = Path(os.environ.get('LAOYU_FEEDBACK_CONFIG_PATH', root / '.build-cache/feedback-channel.json')).resolve()
if feedback_config.is_file():
    import json
    sys.path.insert(0, str(root / 'scripts'))
    from prepare_feedback import valid_webhook
    if feedback_config.name != 'feedback-channel.json' or not valid_webhook(json.loads(feedback_config.read_text(encoding='utf-8')).get('webhook')):
        raise ValueError('Invalid private feedback build configuration')
    datas.append((str(feedback_config), '.'))
elif os.environ.get('LAOYU_ALLOW_UNCONFIGURED_FEEDBACK') != '1':
    raise ValueError('Release build requires feedback configuration; run scripts/prepare_feedback.py')
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
                 info_plist={'CFBundleShortVersionString':__version__,'CFBundleVersion':__version__,'NSHighResolutionCapable':True})
