"""Forensic wrapper for the laoyu-sync 0.3.6->0.3.7 update attempt #4.

- 150ms process churn log (LaoyuSync/msedgewebview2/syncthing)
- continuous handle64 snapshots every ~1.5s filtered to laoyu-sync paths
- extra snapshot right after old LaoyuSync pids die
- receipt (re)appearance logged without crashing
"""
import json
import os
import subprocess
import threading
import time
import urllib.request

DATA = r'C:\Users\Administrator\AppData\Local\LaoyuSync'
RECEIPT = os.path.join(DATA, 'update-result.json')
HANDLE = r'C:\Users\Administrator\AppData\Local\Temp\handle64.exe'
LOG = r'C:\Users\Administrator\AppData\Local\Temp\laoyu-forensic.log'

log_lock = threading.Lock()
logf = open(LOG, 'w', encoding='utf-8')


def log(msg):
    with log_lock:
        logf.write(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {msg}\n")
        logf.flush()


def procs():
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'LaoyuSync|msedgewebview2|syncthing' } | ForEach-Object { \"$($_.ProcessId):$($_.ParentProcessId):$($_.Name)\" }"],
        capture_output=True, text=True, timeout=10).stdout.split()
    return sorted(out)


def handle_snap(tag):
    def run():
        try:
            r = subprocess.run([HANDLE, '-accepteula', '-a', '-u', 'laoyu-software-center'],
                               capture_output=True, text=True, timeout=60)
            with log_lock:
                logf.write(f'--- HANDLES {tag} ---\n')
                for line in r.stdout.splitlines():
                    logf.write('H ' + line + '\n')
                logf.write(f'--- END {tag} ---\n')
                logf.flush()
        except Exception as exc:
            log(f'HANDLES {tag} ERROR {exc}')
    threading.Thread(target=run, daemon=True).start()


def main():
    last = set(procs())
    log(f'baseline procs: {last}')
    receipt_prev = open(RECEIPT, encoding='utf-8').read()[:400] if os.path.exists(RECEIPT) else 'none'
    log(f'baseline receipt: {receipt_prev[:120]}')

    cfg = json.load(open(os.path.join(DATA, 'config.json'), encoding='utf-8'))
    req = urllib.request.Request('http://127.0.0.1:8390/api/update/start',
                                 data=b'{}', method='POST',
                                 headers={'Host': '127.0.0.1:8390', 'X-Token': cfg['token'],
                                          'Content-Type': 'application/json'})
    started = json.load(urllib.request.urlopen(req, timeout=30))
    log(f'update/start -> {started}')

    deadline = time.time() + 240
    n = 0
    old_pids = {p for p in last if 'LaoyuSync' in p}
    death_snapped = False
    stop = False
    while not stop and time.time() < deadline:
        cur = set(procs())
        if cur != last:
            for gone in sorted(last - cur):
                log(f'PROC-GONE {gone}')
            for new in sorted(cur - last):
                log(f'PROC-NEW {new}')
            last = cur
        now_live = {p for p in cur if 'LaoyuSync' in p}
        if old_pids and not (now_live & old_pids) and not death_snapped:
            death_snapped = True
            log('>>> old LaoyuSync pids gone; snapshot + start fast cadence')
            handle_snap(f'old-death-{n}'); n += 1
        if death_snapped and n < 8:
            handle_snap(f'cont{n}'); n += 1
            time.sleep(1.2)
        if os.path.exists(RECEIPT):
            body = open(RECEIPT, encoding='utf-8').read()
            key = body[:400]
            if key != receipt_prev:
                receipt_prev = key
                log(f'RECEIPT: {key}')
                handle_snap(f'receipt-{n}'); n += 1
                stop = True
        time.sleep(0.15)
    time.sleep(4)
    handle_snap('final')
    time.sleep(2)
    logf.close()


if __name__ == '__main__':
    main()
