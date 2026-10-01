"""Feedback requires an explicit receipt; HTTP success alone is insufficient."""
import io
import hashlib
import threading
import time
import zipfile
import json
import platform
import re
import urllib.parse
import urllib.request
import uuid
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
    try:
        request_id = str(uuid.UUID(str(body.get('request_id') or uuid.uuid4())))
    except ValueError:
        raise ValueError('反馈编号不正确') from None
    return {'product': 'laoyu-sync', 'request_id': request_id, 'version': version.__version__, 'platform': platform.system(),
            'category': category, 'text': text, 'logs': diagnostics(engine_key) if include else None}


_SEND_LOCK = threading.Lock()


def _robot_url(url):
    parsed = urllib.parse.urlsplit(url)
    keys = urllib.parse.parse_qs(parsed.query)
    if parsed.scheme != 'https' or parsed.netloc != 'qyapi.weixin.qq.com' or parsed.path != '/cgi-bin/webhook/send' or set(keys) != {'key'} or len(keys['key']) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', keys['key'][0]) or parsed.fragment:
        raise ValueError('企业微信机器人地址不正确')
    return parsed, keys['key'][0]


def _request(url, body, content_type='application/json'):
    req = urllib.request.Request(url, data=body, headers={'Content-Type':content_type, 'User-Agent':'LaoyuSync/' + version.__version__})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read(65537))
    except Exception:
        raise ValueError('企业微信暂未确认接收，请稍后重试；内容已保留') from None
    if not isinstance(result, dict) or result.get('errcode') != 0:
        code = result.get('errcode') if isinstance(result, dict) else None
        raise ValueError('企业微信未确认接收（错误码：' + str(code) + '），请稍后重试')
    return result


def _upload(url, data):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('diagnostics.txt', data['logs'])
        bundle.writestr('feedback.txt', '编号：' + data['request_id'] + '\n版本：' + data['version'] + '\n系统：' + data['platform'] + '\n分类：' + data['category'] + '\n留言：\n' + data['text'])
    content = archive.getvalue()
    boundary = 'LaoyuSync' + uuid.uuid4().hex
    head = ('--' + boundary + '\r\nContent-Disposition: form-data; name="media"; filename="laoyu-sync-diagnostics-' + data['request_id'][:8] + '.zip"; filelength=' + str(len(content)) + '\r\nContent-Type: application/octet-stream\r\n\r\n').encode('ascii')
    body = head + content + ('\r\n--' + boundary + '--\r\n').encode('ascii')
    parsed, key = _robot_url(url)
    upload = 'https://' + parsed.netloc + '/cgi-bin/webhook/upload_media?' + urllib.parse.urlencode({'key':key,'type':'file'})
    result = _request(upload,body,'multipart/form-data; boundary=' + boundary)
    if not isinstance(result.get('media_id'), str) or not result['media_id']:
        raise ValueError('企业微信没有返回日志附件编号，请重试')
    return result['media_id']


def _messages(data):
    # Robot text messages are limited to 2048 UTF-8 bytes, not characters.
    chunks, current = [], ''
    for character in data['text']:
        if len((current + character).encode('utf-8')) > 1600:
            chunks.append(current); current = ''
        current += character
    if current:
        chunks.append(current)
    header = ('【捞鱼同步小助手 · 反馈】\n版本：' + data['version'] + '\n系统：' + data['platform'] + '\n分类：' + data['category'] + '\n编号：' + data['request_id'][:8])
    return [header + f'\n留言（{i+1}/{len(chunks)}）：\n' + text for i,text in enumerate(chunks)]


def submit(body, engine_key=''):
    data = payload(body, engine_key)
    url = config.get('feedback_url')
    if not url:
        raise ValueError('企业微信反馈渠道尚未配置；内容已保留，没有发送')
    _robot_url(url)
    signature = hashlib.sha256(json.dumps([url,data['text'],data['category'],data['logs'] is not None],ensure_ascii=False).encode()).hexdigest()
    with _SEND_LOCK:
        saved = config.get('feedback_delivery_receipts') or {}
        saved = {key:value for key,value in saved.items() if isinstance(value,dict) and time.time()-value.get('updated',0) < 2*86400}
        state = saved.get(data['request_id'])
        if state and state.get('signature') != signature:
            raise ValueError('反馈内容已改变，请重新提交')
        state = state or {'signature':signature,'text_sent':0,'file_sent':False,'updated':time.time()}
        def remember():
            state['updated'] = time.time()
            saved[data['request_id']] = state
            config.set('feedback_delivery_receipts', dict(sorted(saved.items(), key=lambda item:item[1]['updated'])[-20:]))
        if not state.get('complete'):
            if state.get('media_id') and time.time() - state.get('media_created', 0) > 2 * 86400:
                state.pop('media_id')
            if data['logs'] is not None and not state.get('media_id'):
                state['media_id'] = _upload(url,data)
                state['media_created'] = time.time()
                remember()
            messages = _messages(data)
            for index in range(state['text_sent'],len(messages)):
                _request(url,json.dumps({'msgtype':'text','text':{'content':messages[index]}},ensure_ascii=False).encode('utf-8'))
                state['text_sent'] = index+1
                remember()
            if data['logs'] is not None and not state['file_sent']:
                try:
                    _request(url,json.dumps({'msgtype':'file','file':{'media_id':state['media_id']}}).encode('utf-8'))
                except ValueError:
                    raise ValueError('留言已被企业微信确认接收，但日志附件未确认；重试会继续发送附件，内容已保留') from None
                state['file_sent'] = True
                remember()
            state['complete'] = True
            remember()
    return {'ok':True,'receipt_id':data['request_id'],'delivery':'wecom_direct','logs_attached':data['logs'] is not None}
