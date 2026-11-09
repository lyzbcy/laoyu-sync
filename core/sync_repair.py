"""Diagnose current Syncthing state and run a bounded retry when explicitly requested."""
from pathlib import Path
import shutil
import threading
import time
from urllib.parse import urlencode

import activity
import stmanager
import wizard

_LOCK = threading.Lock()
_RETRY_INTERVAL = 60
_MIN_FREE_BYTES = 128 * 1024 * 1024
_RETRY_LIMIT = 3
_LAST_RETRY = float('-inf')

ERRORS = (
    ('source', ('no connected device', 'no device has', 'no device to download', 'no source device'),
     '对端暂无可用数据块', '让保存最新文件的电脑上线，确认它已接受这个项目。'),
    ('disk', ('no space left', 'not enough space', 'disk full', 'insufficient space'),
     '磁盘空间不足', '释放项目所在磁盘的空间，随后引擎会继续尝试。'),
    ('permission', ('permission denied', 'access is denied', 'access denied', 'operation not permitted'),
     '项目文件权限不足', '检查当前系统账号对这个项目目录和文件的读写权限。'),
    ('path', ('no such file', 'cannot find the path', 'cannot find the file', 'folder marker', 'folder path missing'),
     '路径或同步标记不可用', '检查磁盘是否挂载、项目原路径和同步标记是否仍在。'),
    ('name', ('invalid filename', 'invalid file name', 'invalid windows filename', 'case conflict', 'case collision',
              'filename is too long', 'file name too long', 'filename is invalid'),
     '文件名或路径不兼容', '在来源电脑核对文件名、大小写冲突和路径长度。'),
    ('busy', ('sharing violation', 'used by another process', 'resource busy',
              'lock violation', 'being used by another'),
     '文件暂时被占用', '关闭占用文件的软件。自动修复可以对仍在原位的文件发起一次定向扫描。'),
)


def classify(message):
    lower = message.lower()
    for code, phrases, title, action in ERRORS:
        if any(phrase in lower for phrase in phrases):
            return code, title, action
    return 'unknown_error', '引擎报告同步失败', '查看原始原因，处理后引擎会继续尝试。'


def issue(code, title, action, **detail):
    return {'code': code, 'title': title, 'action': action, **detail}


def folder_issues(manager, folder, devices):
    label = folder['label']
    if folder.get('paused'):
        yield issue('paused', '项目已暂停', '确认要恢复时，在同步项目中点击继续。', folder=label)
        return
    path = Path(folder['path']).expanduser()
    if not folder['path'] or not path.is_dir():
        yield issue('path', '项目目录当前不可用', '检查原位置、移动硬盘或挂载路径。', folder=label)
        return

    shared = [devices.get(did) for did in folder.get('deviceIDs', [])]
    online = any(d and d.get('connected') for d in shared)
    if not shared:
        yield issue('unshared', '项目尚未共享', '到同步项目选择要共享的设备。', folder=label)
    elif not online:
        yield issue('offline', '共享设备均未连接', '打开另一台电脑上的同步助手并确认配对。', folder=label)
    elif any(not d or not d.get('connected') for d in shared):
        yield issue('partial_offline', '部分共享设备离线', '在线设备仍可继续同步；离线设备上线后再接收。', folder=label)

    if folder.get('state') == 'unavailable':
        yield issue('unavailable', '项目状态暂时不可读', '稍后重新排查，或复制诊断日志。', folder=label)
        return
    failed = folder.get('pullErrors') or folder.get('errors') or folder.get('state') == 'error'
    if failed:
        try:
            errors = manager.folder_error_items(folder['id'], limit=5)
        except (OSError, RuntimeError, ValueError, TypeError):
            errors = []
        if not errors:
            yield issue('unknown_error', '引擎报告同步失败', '暂未取到文件级原因，请稍后重试或复制诊断日志。', folder=label)
        for item in errors:
            code, title, action = classify(item['message'])
            yield issue(code, title, action, folder=label, file=item['path'],
                        evidence=item['message'], candidate=(folder['id'], item['path']) if online and code == 'busy' else None)
    elif folder.get('needItems', folder.get('needFiles', 0)):
        yield issue('pending', '还有文件或目录等待同步', '引擎会继续重试；稍后刷新确认进度。', folder=label)


def diagnose(manager):
    snap = manager.status()
    engine = snap['syncthing']
    if not engine['api_ok']:
        startup = engine.get('startup', {})
        code = startup.get('error_code')
        checking = startup.get('phase') in ('starting', 'checking')
        retry = not checking and not engine.get('running') and code in ('unavailable', 'timeout', 'engine_exited', 'launch_failed')
        return [issue('engine_start' if retry else 'engine_unavailable', '同步引擎正在启动' if checking else '暂时连接不上同步引擎',
                      startup.get('message') or '确认引擎已运行后再试。')]
    if not snap['folders']:
        setup = snap.get('setup', {})
        return [issue('setup', setup.get('title') or '还没有同步项目', setup.get('detail') or '配对后添加一个文件夹。')]
    devices = {d['id']: d for d in snap['devices'] if not d['self']}
    issues = [i for f in snap['folders'] for i in folder_issues(manager, f, devices)]
    delivery = snap.get('delivery', {}).get('state')
    if not issues and delivery == 'sending':
        issues.append(issue('sending', '对端正在接收', '等待对端完成，随后再确认送达状态。'))
    if not issues and delivery == 'unknown':
        issues.append(issue('unconfirmed', '暂时无法确认对端完成度', '可在对端打开同步项目确认接收状态。'))
    return issues


def retry_file(manager, fid, relative):
    """Revalidate the current configuration and only scan an existing regular file."""
    config = next((f for f in manager.client.get('/rest/config').get('folders', []) if f.get('id') == fid), None)
    if not config or not config.get('path') or config.get('paused') or not fid or not relative:
        return False
    raw = Path(relative)
    if raw.is_absolute() or raw.drive or any(part == '..' or ':' in part for part in raw.parts) or not raw.name or '\x00' in relative:
        return False
    connections = manager.client.get('/rest/system/connections', timeout=2).get('connections', {})
    if not any(connections.get(device.get('deviceID'), {}).get('connected') is True
               for device in config.get('devices', [])):
        return False
    errors = manager.folder_error_items(fid, limit=5)
    if not any(item['path'] == relative and classify(item['message'])[0] == 'busy' for item in errors):
        return False
    try:
        folder = Path(config['path']).expanduser().resolve(strict=True)
        marker = Path(config.get('markerName') or '.stfolder')
        target = (folder / raw).resolve(strict=True)
        if (marker.is_absolute() or marker.parent != Path('.') or marker.name in ('', '..')
                or not (folder / marker).exists()
                or not target.is_relative_to(folder) or target != folder / raw or not target.is_file()
                or shutil.disk_usage(folder).free < _MIN_FREE_BYTES):
            return False
    except (OSError, RuntimeError, ValueError):
        return False
    manager.client.post('/rest/db/scan?' + urlencode({'folder': fid, 'sub': raw.as_posix()}), timeout=8)
    return True


def run(manager, repair=False):
    global _LAST_RETRY
    if not repair:
        return {'issues': [{k: v for k, v in i.items() if k != 'candidate'} for i in diagnose(manager)], 'actions': []}
    if not _LOCK.acquire(blocking=False):
        return {'issues': [], 'actions': [], 'notice': '已有同步修复正在运行。'}
    try:
        issues = diagnose(manager)
        candidates = list(dict.fromkeys(i['candidate'] for i in issues if i.get('candidate')))[:_RETRY_LIMIT]
        can_start = any(i['code'] == 'engine_start' for i in issues)
        actions = []
        notice = ''
        if (can_start or candidates) and time.monotonic() - _LAST_RETRY < _RETRY_INTERVAL:
            notice = '刚重试过，请等一分钟再执行修复。'
        elif can_start:
            if stmanager.selected_engine_running(stmanager.engine_home()) is False:
                _LAST_RETRY = time.monotonic()
                healthy = manager.ensure_running(wait_seconds=12)
                actions.append('同步引擎已重新接通。' if healthy else '已尝试启动，引擎仍未就绪。')
            else:
                notice = '检测到现有引擎或进程状态不明，请先在原工具中检查。'
        elif candidates:
            _LAST_RETRY = time.monotonic()
            for fid, relative in candidates:
                try:
                    with wizard.MUTATION_LOCK:
                        accepted = retry_file(manager, fid, relative)
                    actions.append('已完成一次定向扫描，等待引擎重新同步。' if accepted else '文件或项目不符合安全重试条件，已跳过。')
                except (OSError, RuntimeError, ValueError, TypeError):
                    actions.append('引擎未完成定向扫描，请关闭占用文件的程序后再试。')
        else:
            notice = '当前没有可安全自动重试的故障。'
        if actions:
            activity.user(f'同步排查执行了 {len(actions)} 项本机重试。')
            issues = diagnose(manager)
        return {'issues': [{k: v for k, v in i.items() if k != 'candidate'} for i in issues],
                'actions': actions, 'notice': notice}
    finally:
        _LOCK.release()
