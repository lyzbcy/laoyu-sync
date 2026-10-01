"""Loopback-only feedback relay; public access goes through existing HTTPS nginx."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
import zipfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TTL = 7 * 86400


class Relay:
    def __init__(self, directory, base_url, webhook):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip('/')
        self.webhook = webhook
        self.lock = threading.Lock()
        self.recent = {}

    def clean(self):
        cutoff = time.time() - TTL
        for path in self.directory.glob('*'):
            if path.suffix in ('.json', '.zip') and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    def submit(self, data, address):
        if data.get('product') != 'laoyu-sync':
            raise ValueError('不支持的软件')
        for field, limit in [('text', 4000), ('category', 40), ('version', 30), ('platform', 30)]:
            if not isinstance(data.get(field), str) or not data[field].strip() or len(data[field]) > limit:
                raise ValueError('反馈内容不正确')
        logs = data.get('logs')
        try:
            uuid.UUID(data['request_id'])
        except (KeyError, ValueError, TypeError):
            raise ValueError('反馈编号不正确') from None
        if logs is not None and (not isinstance(logs, str) or len(logs.encode('utf-8')) > 32000):
            raise ValueError('诊断日志过大')
        # Serialize delivery to avoid concurrent duplicate retries and robot bursts.
        with self.lock:
            self.clean()
            now = time.time()
            self.recent = {k: [t for t in v if now - t < 600] for k, v in self.recent.items() if any(now-t < 600 for t in v)}
            recent = self.recent.setdefault(address, [])
            digest = hashlib.sha256(data['request_id'].encode()).hexdigest()
            saved = self.directory / (digest + '.json')
            if saved.is_file() and now - saved.stat().st_mtime < 600:
                return json.loads(saved.read_text(encoding='utf-8'))
            if len(recent) >= 5 or sum(map(len, self.recent.values())) >= 60:
                raise ValueError('提交过于频繁，请稍后重试')
            if sum(p.stat().st_size for p in self.directory.glob('*') if p.is_file()) > 256 * 1024 * 1024:
                raise ValueError('反馈存储暂时已满，请稍后重试')
            recent.append(now)
            receipt = secrets.token_urlsafe(24)
            archive = self.directory / (receipt + '.zip')
            log_url = None
            if logs is not None:
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
                    bundle.writestr('diagnostics.txt', logs)
                log_url = self.base_url + '/logs/' + receipt + '.zip'
            message = ('【捞鱼同步小助手 · 用户反馈】\n版本：' + data['version'] + '\n系统：' + data['platform']
                       + '\n分类：' + data['category'] + '\n留言：\n' + data['text']
                       + ('\n诊断日志（7天有效）：\n' + log_url if log_url else '\n诊断日志：用户选择不附带'))
            # WeCom markdown content has a byte limit, including Chinese and URLs.
            if len(message.encode('utf-8')) > 3800:
                if logs is not None:
                    with zipfile.ZipFile(archive, 'a', zipfile.ZIP_DEFLATED) as bundle:
                        bundle.writestr('feedback.txt', data['text'])
                    message = message.split('留言：\n')[0] + '留言：\n' + data['text'].encode('utf-8')[:1800].decode('utf-8','ignore') + '\n（完整留言在日志包内）\n' + log_url
                else:
                    # Never silently truncate an opt-out user's feedback.
                    raise ValueError('不附日志时留言最多约1000字，请精简后重试')
            request = urllib.request.Request(self.webhook, data=json.dumps({'msgtype':'text','text':{'content':message}},ensure_ascii=False).encode(), headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    result = json.loads(response.read(65536))
                if result.get('errcode') != 0:
                    raise ValueError('机器人未确认接收')
            except Exception:
                archive.unlink(missing_ok=True)
                raise ValueError('机器人未确认接收，内容未记为送达') from None
            result = {'ok':True,'delivered':True,'receipt_id':receipt,'logs_url':log_url}
            temporary = saved.with_suffix('.tmp')
            temporary.write_text(json.dumps(result), encoding='utf-8')
            temporary.replace(saved)
            return result

    def log(self, name):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32}\.zip', name):
            return None
        path = self.directory / name
        if not path.is_file() or time.time() - path.stat().st_mtime > TTL:
            return None
        return path.read_bytes()


def handler(relay):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/v1/submit':
                return self.reply({'ok':False},404)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('请求过大或为空')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('请求格式不正确')
                result = relay.submit(data, self.headers.get('X-Real-IP', self.client_address[0]))
                self.reply(result)
            except (ValueError, TypeError):
                self.reply({'ok':False,'error':'未完成送达，请检查留言长度或稍后重试'},400)

        def do_GET(self):
            if self.path == '/health':
                return self.reply({'ok':True,'service':'laoyu-sync-feedback'})
            if self.path.startswith('/logs/'):
                body = relay.log(self.path[6:])
                if body is not None:
                    self.send_response(200)
                    self.send_header('Content-Type','application/zip')
                    self.send_header('Content-Disposition','attachment; filename="laoyu-sync-diagnostics.zip"')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Content-Length',str(len(body)))
                    self.end_headers()
                    return self.wfile.write(body)
            self.reply({'ok':False},404)
    return Handler


if __name__ == '__main__':
    webhook = os.environ['LAOYU_FEEDBACK_WEBHOOK']
    base = os.environ['LAOYU_FEEDBACK_BASE_URL']
    if not base.startswith('https://') or not webhook.startswith('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='):
        raise SystemExit('Invalid feedback service configuration')
    relay = Relay(os.environ.get('LAOYU_FEEDBACK_DATA','/var/lib/laoyu-sync-feedback'),base,webhook)
    server = ThreadingHTTPServer(('127.0.0.1',18774),handler(relay))
    server.serve_forever()
