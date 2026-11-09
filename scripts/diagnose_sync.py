"""Local CLI for the same diagnostics and guarded repair used by the app."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
import config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', action='store_true', help='Run the same safe retries as the app button')
    args = parser.parse_args()
    try:
        current = json.loads(config.CONFIG_PATH.read_text(encoding='utf-8'))
        port = int(os.environ.get('LAOYU_SYNC_PORT', current.get('port', 8390)))
        route = 'sync-repair' if args.repair else 'sync-diagnose'
        request = Request(f'http://127.0.0.1:{port}/api/{route}',
                          data=b'{}' if args.repair else None,
                          headers={'X-Token': current['token'], 'Content-Type': 'application/json'})
        with build_opener(ProxyHandler({})).open(request, timeout=90) as response:
            print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
    except HTTPError as exc:
        print(f'本机助手拒绝排查请求（HTTP {exc.code}）。请确认已运行支持该功能的版本。', file=sys.stderr)
        return 1
    except (OSError, URLError, ValueError, KeyError):
        print('无法读取本机同步助手。请先打开助手，再运行排查。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
