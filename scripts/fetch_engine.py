"""Fetch pinned upstream binary and verify official checksum before extraction."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import urllib.request
import zipfile

VERSION = '2.1.5'
BASE = f'https://github.com/syncthing/syncthing/releases/download/v{VERSION}/'

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'LaoyuSync-Build'})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=['windows-amd64', 'macos-arm64', 'macos-amd64'], default='windows-amd64')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    cache = root / '.build-cache'
    cache.mkdir(exist_ok=True)
    suffix = '.zip' if args.platform.startswith('windows') else '.tar.gz'
    name = f'syncthing-{args.platform}-v{VERSION}{suffix}'
    checksums = fetch(BASE + 'sha256sum.txt.asc').decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.strip().endswith(name))
    archive = cache / name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        archive.write_bytes(fetch(BASE + name))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Official Syncthing checksum mismatch')
    engine = root / 'engine'
    engine.mkdir(exist_ok=True)
    binary = 'syncthing.exe' if suffix == '.zip' else 'syncthing'
    if suffix == '.zip':
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                basename = Path(entry.filename).name
                if basename in (binary, 'LICENSE.txt', 'AUTHORS.txt'):
                    (engine / basename).write_bytes(z.read(entry))
    else:
        with tarfile.open(archive) as t:
            for entry in t.getmembers():
                basename = Path(entry.name).name
                if entry.isfile() and basename in (binary, 'LICENSE.txt', 'AUTHORS.txt'):
                    (engine / basename).write_bytes(t.extractfile(entry).read())
        (engine / binary).chmod(0o755)
    (engine / 'UPSTREAM.txt').write_text(f'Syncthing {VERSION}\n{BASE + name}\nSHA256 {expected}\nSource: https://github.com/syncthing/syncthing/tree/v{VERSION}\n', encoding='utf-8')
    print('Verified', name, expected)

if __name__ == '__main__':
    main()
