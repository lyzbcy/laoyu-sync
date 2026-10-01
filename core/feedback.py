"""Feedback requires an explicit receipt; HTTP success alone is insufficient."""
import json
import platform
import re
import urllib.parse
import urllib.request
import config
import version

CATEGORIES = ('未分类', '连接与配对', '已有项目识别', '文件同步', '桌面小鱼', '安装与更新', '建议与评价', '其他')


def diagnostics(engine_key=''):
    path = config.LOG_DIR / 'syncsprite.log'
    text = path.read_bytes()[-24000:].decode('utf-8', errors='replace') if path.is_file() else ''
    for value in (config.get('token'), engine_key, config.get('feedback_url')):
        if value:
            text = text.replace(value, '[已隐藏]')
    text = re.sub(r'(?i)((?:token|apikey|api-key|key|password|secret)\s*[=:]\s*)[^\s&,"<>]+', r'\1[已隐藏]', text)
    text = re.sub(r'\b(?:[A-Z2-7]{7}-){7}[A-Z2-7]{7}\b', '[设备号码]', text)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '[网络地址]', text)
    text = re.sub(r'[A-Za-z]:[\\/][^\r\n"<>]+', '[本机路径]', text)
    text = re.sub(r'/(?:Users|home)/[^\r\n"<>]+', '[本机路径]', text)
    return 'Laoyu Sync ' + version.__version__ + '\n' + text


def payload(body, engine_key=''):
    text = str(body.get('text') or '').strip()
    if not text or len(text) > 4000:
        raise ValueError('请填写反馈备注（最多4000字）')
    category = body.get('category') or '未分类'
    if category not in CATEGORIES:
        raise ValueError('反馈分类不正确')
    include = body.get('include_logs', True)
    if not isinstance(include, bool):
        raise ValueError('日志选项不正确')
    return {'product': 'laoyu-sync', 'version': version.__version__, 'platform': platform.system(),
            'category': category, 'text': text, 'logs': diagnostics(engine_key) if include else None}


def submit(body, engine_key=''):
    data = payload(body, engine_key)
    url = config.get('feedback_url')
    if not url:
        raise ValueError('反馈接收服务尚未开通；内容已保留，没有发送')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('反馈服务地址不正确')
    # Group webhook credentials stay on the relay, never in a distributed client.
    if parsed.hostname == 'qyapi.weixin.qq.com':
        raise ValueError('请配置反馈接收服务，群机器人密钥不能随客户端发布')
    req = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'LaoyuSync/' + version.__version__})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            receipt = json.loads(resp.read(65537).decode('utf-8'))
    except Exception:
        raise ValueError('发送失败或尚未收到确认；内容已保留，请稍后重试') from None
    if not isinstance(receipt, dict) or receipt.get('ok') is not True or receipt.get('delivered') is not True or not receipt.get('receipt_id'):
        raise ValueError('接收方没有确认送达；内容已保留，请稍后重试')
    if data['logs'] is not None:
        log_url = urllib.parse.urlsplit(str(receipt.get('logs_url') or ''))
        if log_url.scheme != 'https' or not log_url.hostname:
            raise ValueError('接收方没有返回日志链接，尚不能确认完整反馈成功')
    return {'ok': True, 'receipt_id': str(receipt['receipt_id']), 'logs_url': receipt.get('logs_url') if data['logs'] is not None else None}
