"""Emit platform-specific metadata from the immutable ditto ZIP."""
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'core'))
from version import __version__

bundle = root / 'dist/LaoyuSync.app'
info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
if info.get('CFBundleShortVersionString') != __version__:
    raise SystemExit('Mac bundle version mismatch')
channel = bundle / 'Contents/Resources/feedback-channel.json'
if not channel.is_file():
    raise SystemExit('Mac release feedback channel missing')
arch = platform.machine()
name = f'laoyu-sync-{__version__}-macos-{arch}.zip'
archive = root / 'dist' / name
value = dict(version=__version__, platform='macos-' + arch,
    download_url=f'https://github.com/lyzbcy/laoyu-sync/releases/download/v{__version__}/{name}',
    sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), sizeBytes=archive.stat().st_size)
(root / 'dist/version-macos.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
print(name, value['sha256'])
