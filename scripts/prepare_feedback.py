"""Prepare a private build input; never print or commit the robot credential."""
import json
import os
from pathlib import Path
import re
import urllib.parse


def valid_webhook(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        query = urllib.parse.parse_qs(parsed.query)
        return (parsed.scheme == 'https' and parsed.netloc == 'qyapi.weixin.qq.com'
                and parsed.path == '/cgi-bin/webhook/send' and not parsed.fragment
                and set(query) == {'key'} and len(query['key']) == 1
                and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', query['key'][0]) is not None)
    except (ValueError, TypeError):
        return False


def prepare(destination, webhook):
    if not valid_webhook(webhook):
        raise ValueError('正式构建缺少有效反馈渠道；请配置 LAOYU_FEEDBACK_WEBHOOK')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({'webhook': webhook}), encoding='utf-8')
    try:
        destination.chmod(0o600)
    except OSError:
        pass


if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / '.build-cache/feedback-channel.json'
    try:
        prepare(destination, os.environ.get('LAOYU_FEEDBACK_WEBHOOK', '').strip())
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print('Private feedback build configuration prepared')
