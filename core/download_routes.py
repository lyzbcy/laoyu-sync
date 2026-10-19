"""Bounded release-asset probes. Manifests and expected hashes stay on GitHub TLS."""
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.parse
import urllib.request

MIRRORS = (('镜像一', 'https://ghfast.top/'), ('镜像二', 'https://gh-proxy.com/'))


def asset_origin(value):
    """Unwrap only the shipped mirror allowlist; never accept arbitrary proxies."""
    for _, prefix in MIRRORS:
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def candidates(origin):
    parsed = urllib.parse.urlsplit(origin)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or not parsed.path.startswith('/lyzbcy/laoyu-sync/releases/download/')
            or parsed.query or parsed.fragment):
        raise ValueError('下载源不在可信仓库范围内')
    return [('GitHub', origin), *[(name, prefix + origin) for name, prefix in MIRRORS]]


def _probe(route):
    name, url = route
    start = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={'Range': 'bytes=0-16383', 'User-Agent': 'LaoyuSync'})
        with urllib.request.urlopen(request, timeout=4) as response:
            sample = response.read(16384)
        if not sample.startswith((b'PK\x03\x04', b'PK\x05\x06')):
            return None  # HTML challenges and error pages are not ZIP routes.
        return (time.monotonic() - start, name, url)
    except Exception:
        return None


def ranked_routes(origin):
    routes = candidates(origin)
    with ThreadPoolExecutor(max_workers=len(routes)) as pool:
        measured = [result for result in pool.map(_probe, routes) if result is not None]
    measured.sort(key=lambda result: result[0])
    available = [(name, url) for _, name, url in measured]
    # Try unresponsive origins last, with normal download timeout and hash checks.
    return available + [route for route in routes if route not in available]


def download(origin, destination, expected_hash, on_progress):
    import hashlib
    import re
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_hash):
        raise ValueError('缺少下载包校验值')
    last_error = '下载线路不可用'
    bad_hash = False
    for name, url in ranked_routes(origin):
        received = 0
        digest = hashlib.sha256()
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'LaoyuSync'})
            with urllib.request.urlopen(request, timeout=20) as response, destination.open('wb') as stream:
                total = int(response.headers.get('Content-Length', 0))
                while chunk := response.read(256 * 1024):
                    received += len(chunk)
                    if received > 256 * 1024**2:
                        raise ValueError('下载包超过大小限制')
                    stream.write(chunk)
                    digest.update(chunk)
                    on_progress(min(85, int(received / total * 85)) if total else 0,
                                f'{name} · 已下载 {received // 1024} KB')
            if digest.hexdigest() != expected_hash.lower():
                bad_hash = True
                raise ValueError('下载校验失败，未执行更新')
            return name
        except Exception as error:
            # Every attempt truncates its own partial file; no unverified bytes execute.
            last_error = str(error)
            on_progress(0, f'{name} 未完成，正在尝试其他线路')
    raise ValueError(('下载校验失败，未执行更新；' if bad_hash else '') + '所有下载线路均未完成：' + last_error)
