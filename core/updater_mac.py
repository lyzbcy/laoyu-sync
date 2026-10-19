"""macOS .app update transaction. Everything lives beside the installed bundle."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

import config


def app_root(executable=None):
    binary = Path(executable or sys.executable)
    root = binary.parent.parent.parent
    if (root.suffix != '.app' or binary.parent.name != 'MacOS'
            or binary.parent.parent.name != 'Contents' or root.is_symlink()):
        raise ValueError('请从已安装的 Mac 应用打开小助手后重试更新')
    return root.resolve()


def validate_bundle(bundle, expected_version):
    bundle = Path(bundle)
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    if (info.get('CFBundleIdentifier') != 'studio.laoyu.sync'
            or info.get('CFBundleShortVersionString') != expected_version
            or info.get('CFBundleExecutable') != 'LaoyuSync'):
        raise ValueError('Mac 更新包身份或版本不匹配')
    binary = bundle / 'Contents/MacOS/LaoyuSync'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('Mac 更新包缺少可执行主程序')
    return binary


def safe_extract(archive, target, expected_version):
    """Regular files first, internal links last; never write through archive links."""
    target = Path(target).resolve()
    if any(target.iterdir()):
        raise ValueError('Mac 更新解压目录必须为空')
    links, entries, names = {}, [], set()
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 5000 or sum(i.file_size for i in bundle.infolist()) > 512 * 1024**2:
            raise ValueError('Mac 更新包超过安全大小限制')
        for entry in bundle.infolist():
            # ditto writes UTF-8 names without the ZIP UTF-8 flag. Recover the
            # original bytes before validating paths, including Chinese assets.
            filename = entry.filename
            if not entry.flag_bits & 0x800:
                try:
                    filename = filename.encode('cp437').decode('utf-8')
                except UnicodeError:
                    pass
            parts = PurePosixPath(filename).parts
            if (not parts or filename.startswith('/') or '\\' in filename
                    or any(p in ('.', '..') or ':' in p for p in parts)):
                raise ValueError('Mac 更新包含不安全路径')
            if parts[0] == '__MACOSX':
                continue
            if parts[0] != 'LaoyuSync.app':
                raise ValueError('Mac 更新包只能包含 LaoyuSync.app')
            name = '/'.join(parts).casefold()
            if name in names:
                raise ValueError('Mac 更新包含重复路径')
            names.add(name)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                raise ValueError('Mac 更新包含特殊文件')
            if kind == stat.S_IFLNK:
                if entry.file_size > 4096:
                    raise ValueError('Mac 更新链接过长')
                link = bundle.read(entry).decode('utf-8')
                destination = (target.joinpath(*parts).parent / link).resolve()
                if Path(link).is_absolute() or not destination.is_relative_to(target / 'LaoyuSync.app'):
                    raise ValueError('Mac 更新链接越界')
                links[tuple(parts)] = link
            entries.append((entry, parts))
        for entry, parts in entries:
            if any(tuple(parts[:n]) in links for n in range(1, len(parts))):
                raise ValueError('Mac 更新禁止通过链接写入文件')
            if tuple(parts) in links:
                continue
            destination = target.joinpath(*parts)
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, destination.open('xb') as stream:
                    shutil.copyfileobj(source, stream)
                destination.chmod((entry.external_attr >> 16) & 0o777 or 0o644)
        for parts, link in links.items():
            destination = target.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(link)
        result = target / 'LaoyuSync.app'
        for parts in links:
            if not target.joinpath(*parts).resolve(strict=True).is_relative_to(result):
                raise ValueError('Mac 更新链接目标越界')
        validate_bundle(result, expected_version)
        return result


def wait_for_exit(pid, timeout=60):
    if not isinstance(pid, int) or pid <= 1:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(.25)
    return False


def download(info):
    import updater
    import download_routes
    stage, helper_started = None, False
    try:
        target = app_root()
        stage = Path(tempfile.mkdtemp(prefix='.laoyu-update-', dir=target.parent))
        payload = dict(platform='darwin', pid=os.getpid(), target=str(target),
                       replacement=str(stage / 'new/LaoyuSync.app'), stage=str(stage),
                       data=str(config.DATA_DIR), version=info['remote_version'],
                       previous_version=__import__('version').__version__, token=secrets.token_hex(24))
        transaction = stage / 'transaction.json'
        transaction.write_text(json.dumps(payload), encoding='utf-8')
        archive = stage / 'package.zip'
        updater.progress('downloading', 0, '正在比较下载线路（每条最多测速 16 KB）')
        download_routes.download(info['download_url'], archive, info['sha256'],
                                 lambda percent, message: updater.progress('downloading', percent, message))
        updater.progress('verifying', 88, '正在校验 Mac 应用和版本')
        replacement = stage / 'new'
        replacement.mkdir()
        safe_extract(archive, replacement, info['remote_version'])
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(payload['replacement'])],
                       check=True, capture_output=True, timeout=30)
        helper = stage / 'helper.app'
        shutil.copytree(target, helper, symlinks=True)
        if (config.DATA_DIR / 'update-result.json').is_file():
            updater.archive_result('new-update-attempt')
        process = subprocess.Popen([str(helper / 'Contents/MacOS/LaoyuSync'), '--apply-update', str(transaction)],
            cwd=stage, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        deadline = time.monotonic() + 15
        ready = stage / 'helper-ready.json'
        while time.monotonic() < deadline:
            if ready.is_file():
                if json.loads(ready.read_text()).get('token') == payload['token']:
                    helper_started = True
                    break
            if process.poll() is not None:
                raise RuntimeError('Mac 更新助手未能启动，原应用保持运行')
            time.sleep(.1)
        if not helper_started:
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError('Mac 更新助手就绪超时，原应用保持运行')
        updater.progress('restarting', 100, '校验完成，正在重新打开 Mac 应用')
        if updater.EXIT_CALLBACK:
            updater.EXIT_CALLBACK()
        else:
            os._exit(0)
    except Exception as error:
        if stage is not None and not helper_started:
            write_receipt(stage, payload, dict(ok=False, error=str(error)))
        updater.progress('failed', 0, str(error) + '。可重试或从发布页手动下载')


def write_receipt(stage, payload, value):
    data = Path(payload['data'])
    data.mkdir(parents=True, exist_ok=True)
    result = dict(value, version=payload['version'], previous_version=payload.get('previous_version'),
                  target=payload['target'], stage=str(stage), finished_at=time.time(), platform='darwin')
    temporary = data / 'update-result.tmp'
    temporary.write_text(json.dumps(result), encoding='utf-8')
    temporary.replace(data / 'update-result.json')
    if not result.get('recovery'):
        receipt = dict(schema=1, product='laoyu-sync', platform='darwin', stage=str(stage),
            target=payload['target'], data=str(data), version=payload['version'], helper_pid=os.getpid(),
            old_pid=payload['pid'], outcome='complete' if value['ok'] else 'rolled-back', finished_at=time.time())
        (stage / 'cleanup-ready.json').write_text(json.dumps(receipt), encoding='utf-8')


def apply_update(payload_file):
    payload_file = Path(payload_file).resolve()
    payload = json.loads(payload_file.read_text(encoding='utf-8'))
    target_raw = Path(payload['target'])
    stage, target = Path(payload['stage']).resolve(), target_raw.resolve()
    replacement = Path(payload['replacement']).resolve()
    data = Path(payload['data']).resolve()
    if (payload.get('platform') != 'darwin' or payload_file != stage / 'transaction.json'
            or not stage.name.startswith('.laoyu-update-') or stage.parent != target.parent
            or target_raw.is_symlink() or target.suffix != '.app'
            or replacement != stage / 'new/LaoyuSync.app'
            or data.is_relative_to(stage) or data.is_relative_to(target)
            or not isinstance(payload.get('token'), str) or len(payload['token']) != 48):
        raise ValueError('无效 Mac 更新事务')
    validate_bundle(replacement, payload['version'])
    ready = stage / 'helper-ready.tmp'
    ready.write_text(json.dumps({'token': payload['token']}))
    ready.replace(stage / 'helper-ready.json')
    if not wait_for_exit(payload['pid']):
        write_receipt(stage, payload, dict(ok=False, error='无法确认原应用已退出，未替换安装'))
        return
    backup = target.with_name(target.name + '.previous-' + str(time.time_ns()))
    child, swapped = None, False
    try:
        target.rename(backup)
        try:
            replacement.rename(target)
            swapped = True
        except Exception:
            backup.rename(target)
            raise
        ack = stage / 'healthy.json'
        child = subprocess.Popen([str(target / 'Contents/MacOS/LaoyuSync'), '--upgrade-ack', str(ack)],
            cwd=stage, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if ack.is_file():
                health = json.loads(ack.read_text(encoding='utf-8'))
                if health.get('version') == payload['version'] and health.get('engine_ready') is True and health.get('renderer_ready') is True:
                    write_receipt(stage, payload, dict(ok=True, backup=str(backup)))
                    from update_cleanup import register_backup
                    register_backup(target, backup, data, payload['version'])
                    return
            if child.poll() is not None:
                break
            time.sleep(.25)
        raise RuntimeError('新版未完成窗口及引擎就绪确认，正在恢复原版')
    except Exception as error:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
        if backup.is_dir():
            if swapped and target.exists():
                target.rename(stage / 'failed-new.app')
            try:
                backup.rename(target)
                subprocess.Popen([str(target / 'Contents/MacOS/LaoyuSync')], cwd=data,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
            except Exception:
                write_receipt(stage, payload, dict(ok=False, error=str(error), recovery=str(backup)))
                return
        write_receipt(stage, payload, dict(ok=False, error=str(error)))
