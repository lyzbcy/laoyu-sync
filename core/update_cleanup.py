"""Shared cleanup-ready.json protocol; only terminal, owned staging directories."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def process_snapshot():
    if sys.platform == 'darwin':
        result = subprocess.run(['ps', '-axo', 'pid=,args='], capture_output=True, timeout=10)
        if result.returncode:
            raise OSError('Cannot inspect Mac process inventory')
        records = []
        for line in result.stdout.decode('utf-8', errors='replace').splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                raise OSError('Incomplete Mac process inventory')
            records.append(dict(ProcessId=int(parts[0]), ExecutablePath='', CommandLine=parts[1]))
        return records
    if sys.platform != 'win32':
        raise OSError('Windows process inventory required')
    script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; $ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine) | ConvertTo-Json -Compress"
    data = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        encoding='utf-8-sig', creationflags=0x08000000, timeout=20)
    records = json.loads(data)
    if not isinstance(records, list):
        raise OSError('Incomplete process inventory')
    for p in records:
        if p['Name'].lower() in ('laoyusync.exe', 'syncthing.exe', 'python.exe', 'pythonw.exe') and not p.get('ExecutablePath'):
            raise OSError('Cannot inspect related process')
    return records


def safe_tree(parent, folder):
    # 先解析真实路径：macOS /var→/private/var、Windows 8.3 别名（RUNNER~1）等
    # 系统级路径别名不构成重定向；解析后的祖先链不应再含软链/联接，保持纵深防御。
    raw = Path(folder)
    if raw.is_symlink() or (hasattr(raw, 'is_junction') and raw.is_junction()):
        raise ValueError('Redirected stage root')
    parent, folder = Path(parent).resolve(), raw.resolve()
    if folder.parent != parent or not folder.name.startswith('.laoyu-update-'):
        raise ValueError('Not an owned update stage')
    for node in [parent, *parent.parents]:
        if node.is_symlink() or (hasattr(node, 'is_junction') and node.is_junction()):
            raise ValueError('Redirected parent')
    count = 0
    for directory, dirs, files in os.walk(folder, followlinks=False):
        for name in ['', *dirs, *files]:
            node = Path(directory) / name
            count += 1
            internal_mac_link = (sys.platform == 'darwin' and node.is_symlink()
                                 and node.resolve(strict=True).is_relative_to(folder))
            if count > 30000 or (node.is_symlink() and not internal_mac_link) or (hasattr(node, 'is_junction') and node.is_junction()):
                raise ValueError('Redirected or oversized staging tree')
    return folder.resolve()


def cleanup_stage(folder, parent, snapshot=process_snapshot, now=time.time):
    try:
        raw_folder = Path(folder)  # 命令行里可能是未解析的系统别名路径，两种形式都比对
        folder = safe_tree(parent, folder)
        receipt = json.loads((folder / 'cleanup-ready.json').read_text(encoding='utf-8'))
        tx = json.loads((folder / 'transaction.json').read_text(encoding='utf-8'))
        if (receipt.get('schema') != 1 or receipt.get('product') != 'laoyu-sync'
            or receipt.get('outcome') not in ('complete', 'rolled-back', 'superseded')
            or Path(receipt['stage']).resolve() != folder or Path(tx['stage']).resolve() != folder
            or Path(receipt['target']).resolve() != Path(tx['target']).resolve()
            or Path(tx['target']).resolve().parent != folder.parent
            or Path(tx['target']).resolve() == folder
            or Path(tx['data']).resolve().is_relative_to(folder)
            or Path(tx['replacement']).resolve() != (folder / 'new/LaoyuSync.app' if tx.get('platform') == 'darwin' else folder / 'new')
            or Path(receipt['data']).resolve() != Path(tx['data']).resolve()
            or receipt['version'] != tx['version'] or not isinstance(receipt['finished_at'], (int, float))
            or now() - receipt['finished_at'] < 60):
            return False
        for p in snapshot():
            if p['ProcessId'] in (receipt['helper_pid'], receipt['old_pid']):
                return False
            command = (p.get('CommandLine') or '').lower()
            exe = p.get('ExecutablePath') or ''
            stage_refs = {str(folder).lower(), str(raw_folder).lower()}
            expected = Path(tx['target']) / ('Contents/MacOS/LaoyuSync' if tx.get('platform') == 'darwin' else 'LaoyuSync.exe')
            known_installed = ((exe and Path(exe).resolve() == expected.resolve())
                               or command.lstrip('"').startswith(str(expected).lower()))
            if known_installed:
                # The healthy installed app retains its ACK argument, not a stage dependency.
                # Its helper PID has already exited before this receipt can be collected.
                for reference in stage_refs:
                    ack = str(Path(reference) / 'healthy.json').lower()
                    command = command.replace('--upgrade-ack "' + ack + '"', '').replace('--upgrade-ack ' + ack, '')
            if any(ref and ref in command for ref in stage_refs) or (exe and Path(exe).resolve().is_relative_to(folder)):
                return False
        # Preserve transaction and completion evidence outside the directory being removed.
        history = folder.parent / '.laoyu-update-history'
        if history.is_symlink() or (hasattr(history, 'is_junction') and history.is_junction()):
            return False
        history.mkdir(exist_ok=True)
        digest = hashlib.sha256(str(folder).encode()).hexdigest()
        evidence = {'transaction': tx, 'cleanup': receipt, 'cleaned_at': now()}
        with (history / (digest + '.json')).open('w', encoding='utf-8') as out:
            json.dump(evidence, out)
        safe_tree(parent, folder)
        shutil.rmtree(folder)
        return True
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        return False


def mark_superseded_legacy(folder, parent, running_version, snapshot=process_snapshot, now=time.time):
    """Legacy stage: only retire when its old installation is gone and this build supersedes it."""
    from version import semver_tuple
    try:
        folder = safe_tree(parent, folder)
        if (folder / 'cleanup-ready.json').exists():
            return False
        tx_file = folder / 'transaction.json'
        tx = json.loads(tx_file.read_text(encoding='utf-8'))
        target = Path(tx['target']).resolve()
        acknowledged = False
        try:
            ack = json.loads((folder / 'healthy.json').read_text(encoding='utf-8'))
            acknowledged = (ack.get('version') == tx['version'] and ack.get('renderer_ready') is True
                            and ack.get('engine_ready') is True)
        except (OSError, ValueError):
            pass
        try:
            prior = json.loads((Path(tx['data']) / 'update-result.json').read_text(encoding='utf-8'))
            if prior.get('recovery'):
                return False
        except (OSError, ValueError):
            pass
        if (Path(tx['stage']).resolve() != folder or target.parent != folder.parent
            or target == folder or (target.exists() and not acknowledged)
            or Path(tx['replacement']).resolve() != folder / 'new'
            or Path(tx['data']).resolve().is_relative_to(folder)
            or not semver_tuple(tx['version']) or semver_tuple(tx['version']) == (0, 0, 0)
            or semver_tuple(running_version) < semver_tuple(tx['version'])
            or now() - tx_file.stat().st_mtime < 3600):
            return False
        records = snapshot()
        for p in records:
            if p['ProcessId'] == tx['pid'] or str(folder).lower() in (p.get('CommandLine') or '').lower():
                return False
            exe = p.get('ExecutablePath')
            if exe and Path(exe).resolve().is_relative_to(folder):
                return False
        receipt = dict(schema=1, product='laoyu-sync', stage=str(folder), target=str(target),
            data=tx['data'], version=tx['version'], helper_pid=-1, old_pid=tx['pid'],
            outcome='superseded', finished_at=tx_file.stat().st_mtime, running_version=running_version)
        (folder / 'cleanup-ready.json').write_text(json.dumps(receipt), encoding='utf-8')
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False


def cleanup_finished():
    if not getattr(sys, 'frozen', False) or sys.platform not in ('win32', 'darwin'):
        return
    if sys.platform == 'darwin':
        from updater_mac import app_root
        parent = app_root().parent
    else:
        parent = Path(sys.executable).resolve().parent.parent
    import config
    from version import __version__
    cleanup_backups(parent, config.DATA_DIR, __version__)
    for folder in parent.glob('.laoyu-update-*'):
        if folder.is_dir() and folder.name != '.laoyu-update-history':
            from version import __version__
            mark_superseded_legacy(folder, parent, __version__)
            cleanup_stage(folder, parent)


BACKUP_RETENTION_SECONDS = 24 * 3600


def _path_in_command(path, command):
    resolved = str(Path(path).resolve()).lower()
    references = {str(path).lower(), resolved}
    # ps may report /var or /tmp while realpath gives /private/var or /private/tmp.
    if resolved.startswith('/private/'):
        references.add(resolved[len('/private'):])
    return any(reference in command.lower() for reference in references)


def _backup_binary(folder):
    return folder / ('Contents/MacOS/LaoyuSync' if (folder / 'Contents').is_dir() else 'LaoyuSync.exe')


def register_backup(target, backup, data, version):
    """Only a successful renderer+engine health transaction calls this."""
    try:
        backup_alias = str(Path(backup).absolute())
        target, backup, data = Path(target).resolve(), Path(backup).resolve(), Path(data).resolve()
        if (backup.parent != target.parent or not backup.name.startswith(target.name + '.previous-')
                or data.is_relative_to(backup) or data.is_relative_to(target)):
            return False
        receipt = dict(schema=1, product='laoyu-sync', target=str(target), backup=str(backup),
            data=str(data), version=version, healthy=True, finished_at=time.time(), backup_alias=backup_alias,
            target_hash=hashlib.sha256(_backup_binary(target).read_bytes()).hexdigest(),
            backup_hash=hashlib.sha256(_backup_binary(backup).read_bytes()).hexdigest())
        directory = data / 'update-backups'
        if directory.is_symlink():
            return False
        directory.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(str(backup).encode()).hexdigest() + '.json'
        temporary = directory / (name + '.tmp')
        temporary.write_text(json.dumps(receipt), encoding='utf-8')
        temporary.replace(directory / name)
        return True
    except (OSError, ValueError):
        return False  # Retain the backup if its cleanup proof cannot be recorded.


def _safe_backup(parent, backup, target):
    raw = Path(backup)
    if raw.is_symlink() or (hasattr(raw, 'is_junction') and raw.is_junction()):
        raise ValueError('Redirected backup')
    backup, target, parent = raw.resolve(), Path(target).resolve(), Path(parent).resolve()
    if (backup.parent != parent or target.parent != parent or backup == target
            or not backup.name.startswith(target.name + '.previous-') or not backup.is_dir()):
        raise ValueError('Backup is outside its installation parent')
    count = 0
    for directory, dirs, files in os.walk(backup, followlinks=False):
        for name in [*dirs, *files]:
            count += 1
            node = Path(directory) / name
            if (count > 30000 or name in ('config.xml', 'key.pem', 'cert.pem')
                    or (hasattr(node, 'is_junction') and node.is_junction())
                    or (node.is_symlink() and not node.resolve(strict=True).is_relative_to(backup))):
                raise ValueError('Backup contains identity or redirected data')
    return backup


def cleanup_backups(parent, data, running_version, snapshot=process_snapshot, now=time.time):
    """Reclaim receipted, healthy backups after a 24-hour recovery window."""
    from version import semver_tuple
    directory = Path(data) / 'update-backups'
    if not directory.is_dir() or directory.is_symlink():
        return 0
    count = 0
    for receipt_file in directory.glob('*.json'):
        try:
            if receipt_file.is_symlink():
                continue
            receipt = json.loads(receipt_file.read_text(encoding='utf-8'))
            target = Path(receipt['target']).resolve()
            backup = _safe_backup(parent, Path(receipt['backup']), target)
            if (receipt.get('schema') != 1 or receipt.get('product') != 'laoyu-sync'
                    or receipt.get('healthy') is not True
                    or Path(receipt['data']).resolve() != Path(data).resolve()
                    or Path(data).resolve().is_relative_to(backup)
                    or Path(data).resolve().is_relative_to(target)
                    or now() - receipt['finished_at'] < BACKUP_RETENTION_SECONDS
                    or semver_tuple(running_version) == (0, 0, 0)
                    or semver_tuple(receipt['version']) == (0, 0, 0)
                    or semver_tuple(running_version) < semver_tuple(receipt['version'])
                    or not target.is_dir()
                    or hashlib.sha256(_backup_binary(backup).read_bytes()).hexdigest() != receipt['backup_hash']):
                continue
            if (semver_tuple(running_version) == semver_tuple(receipt['version'])
                    and hashlib.sha256(_backup_binary(target).read_bytes()).hexdigest() != receipt['target_hash']):
                continue
            in_use = False
            for process in snapshot():
                command = process.get('CommandLine') or ''
                executable = process.get('ExecutablePath') or ''
                if _path_in_command(receipt.get('backup_alias', backup), command) or (executable and Path(executable).resolve().is_relative_to(backup)):
                    in_use = True
            if in_use:
                continue
            history = Path(data) / 'update-history'
            if history.is_symlink():
                continue
            history.mkdir(exist_ok=True)
            (history / ('backup-' + receipt_file.name)).write_text(
                json.dumps(dict(receipt, cleaned_at=now())), encoding='utf-8')
            _safe_backup(parent, backup, target)  # Re-check the resolved deletion target.
            shutil.rmtree(backup)
            receipt_file.unlink()
            count += 1
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
            continue
    return count
