"""Assemble pending cross-platform metadata from verified immutable CI assets.

This creates files only in the supplied directory; publishing is a separate step.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from prepare_feedback import valid_webhook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from version import __version__


def assemble(directory):
    directory = Path(directory).resolve()
    assets = {}
    channels = {'win-x64': '_internal/feedback-channel.json',
                'macos-arm64': 'LaoyuSync.app/Contents/Resources/feedback-channel.json'}
    for platform, channel in channels.items():
        name = f'laoyu-sync-{__version__}-{platform}.zip'
        archive = directory / name
        with zipfile.ZipFile(archive) as bundle:
            if not valid_webhook(json.loads(bundle.read(channel))['webhook']):
                raise ValueError('Release feedback channel is invalid: ' + platform)
        assets[platform] = dict(download_url=f'https://github.com/lyzbcy/laoyu-sync/releases/download/v{__version__}/{name}',
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), sizeBytes=archive.stat().st_size)
    installer = directory / f'laoyu-sync-{__version__}-win-x64-setup.exe'
    if installer.read_bytes()[:2] != b'MZ':
        raise ValueError('Missing Windows installer')
    manifest = dict(version=__version__, notes='同步优先直连；补齐反馈、Mac一键更新与回退、下载线路、旧版清理和评价入口。',
        **assets['win-x64'], platforms=assets)
    (directory / 'version.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    adapter = json.loads((ROOT / 'launcher-adapter.json').read_text(encoding='utf-8'))
    win = assets['win-x64']
    adapter.update(version=__version__)
    adapter['package'].update(path='dist/' + Path(win['download_url']).name,
        url=win['download_url'], sha256=win['sha256'])
    (directory / 'launcher-adapter.json').write_text(json.dumps(adapter, ensure_ascii=False, indent=2), encoding='utf-8')
    files = [directory / Path(asset['download_url']).name for asset in assets.values()] + [installer]
    checksums = '\n'.join(hashlib.sha256(file.read_bytes()).hexdigest() + '  ' + file.name for file in files) + '\n'
    (directory / f'SHA256SUMS-{__version__}.txt').write_text(checksums, encoding='utf-8')
    print(json.dumps(dict(version=__version__, platforms=list(assets), feedback_configured=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    assemble(parser.parse_args().directory)
