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
    parent, folder = Path(parent).absolute(), Path(folder).absolute()
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
            if count > 30000 or node.is_symlink() or (hasattr(node, 'is_junction') and node.is_junction()):
                raise ValueError('Redirected or oversized staging tree')
    return folder.resolve()


def cleanup_stage(folder, parent, snapshot=process_snapshot, now=time.time):
    try:
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
            or Path(tx['replacement']).resolve() != folder / 'new'
            or Path(receipt['data']).resolve() != Path(tx['data']).resolve()
            or receipt['version'] != tx['version'] or not isinstance(receipt['finished_at'], (int, float))
            or now() - receipt['finished_at'] < 60):
            return False
        for p in snapshot():
            if p['ProcessId'] in (receipt['helper_pid'], receipt['old_pid']):
                return False
            command = (p.get('CommandLine') or '').lower()
            exe = p.get('ExecutablePath') or ''
            if str(folder).lower() in command or (exe and Path(exe).resolve().is_relative_to(folder)):
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
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
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
    if not getattr(sys, 'frozen', False) or sys.platform != 'win32':
        return
    parent = Path(sys.executable).resolve().parent.parent
    for folder in parent.glob('.laoyu-update-*'):
        if folder.is_dir() and folder.name != '.laoyu-update-history':
            from version import __version__
            mark_superseded_legacy(folder, parent, __version__)
            cleanup_stage(folder, parent)
