"""Run the frozen macOS bundle and its actual update helper in isolated profiles."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.request


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, ValueError, KeyError) as error:
            last = error
        time.sleep(.25)
    raise TimeoutError('Mac isolated acceptance timeout: ' + str(last))


def matching_pids(bundle):
    executable = str(bundle / 'Contents/MacOS/LaoyuSync')
    result = subprocess.check_output(['ps', '-axo', 'pid=,args=']).decode('utf-8', errors='replace')
    return [int(parts[0]) for line in result.splitlines()
            if len(parts := line.strip().split(None, 1)) == 2 and parts[0].isdigit()
            and parts[1].startswith(executable)]


def close_marker(bundle):
    return bundle / 'Contents/Resources/ui/__verification_close__.json'


def attach_close_trigger(bundle):
    # Fixture-only UI hook invokes the same native close action as the real button.
    # It is never added to the distributable source bundle.
    path = bundle / 'Contents/Resources/ui/app.js'
    with path.open('a') as stream:
        stream.write('''\nsetInterval(async () => { try {
          const response = await fetch('/__verification_close__.json', {cache:'no-store'});
          if (response.ok && (await response.json()).close && window.pywebview)
            await window.pywebview.api.window_action('close');
        } catch (_) {} }, 500);\n''')


def stop_bundle(bundle):
    close_marker(bundle).write_text('{"close":true}')
    try:
        wait_for(lambda: not matching_pids(bundle), timeout=15)
        return
    except TimeoutError:
        pass
    for pid in matching_pids(bundle):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    wait_for(lambda: not matching_pids(bundle), timeout=20)


def scenario(bundle, profile, fault=False):
    profile.mkdir(parents=True, exist_ok=True)
    target = profile / 'LaoyuSync.app'
    shutil.copytree(bundle, target, symlinks=True)
    attach_close_trigger(target)
    data = profile / 'data'; data.mkdir()
    # No update checks or default pet on this fixture; the channel still comes from the package.
    (data / 'config.json').write_text(json.dumps({'update_manifest_url': '', 'pet_enabled': False}))
    (data / 'identity-marker').write_text('preserve-isolated-user-data')
    env = dict(os.environ, LAOYU_SYNC_DATA=str(data), LAOYU_ST_HOME=str(profile / 'engine'),
               LAOYU_ST_GUI='127.0.0.1:' + str(free_port()), LAOYU_SYNC_PORT=str(free_port()))
    ack = profile / 'old-ready.json'
    old = subprocess.Popen([str(target / 'Contents/MacOS/LaoyuSync'), '--upgrade-ack', str(ack)],
                            env=env, cwd=profile, start_new_session=True)
    helper = None
    result = dict(fault_injected=fault, same_version_fixture=True)
    try:
        health = wait_for(lambda: json.loads(ack.read_text()) if ack.exists() else None)
        assert health.get('renderer_ready') is True and health.get('engine_ready') is True
        token = json.loads((data / 'config.json').read_text())['token']
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def api(path, body=None):
            request = urllib.request.Request('http://127.0.0.1:' + env['LAOYU_SYNC_PORT'] + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'X-Token': token, 'Content-Type': 'application/json'})
            return json.loads(opener.open(request, timeout=5).read())
        assert api('/api/meta')['feedback_url_configured'] is True
        identity = api('/api/mydevice')['id']
        api('/api/settings', {'pet_enabled': True})
        wait_for(lambda: any('--pet' in line for line in subprocess.check_output(['ps','-axo','args=']).decode().splitlines() if str(target) in line))
        api('/api/settings', {'pet_enabled': False})
        stage = profile / '.laoyu-update-test'; stage.mkdir()
        (stage / 'new').mkdir()
        replacement = stage / 'new/LaoyuSync.app'
        shutil.copytree(bundle, replacement, symlinks=True)
        attach_close_trigger(replacement)
        shutil.copytree(bundle, stage / 'helper.app', symlinks=True)
        if fault:
            (replacement / 'Contents/Resources/ui/app.js').write_text('throw new Error("isolated rollback fixture");')
        payload = dict(platform='darwin', pid=old.pid, target=str(target), replacement=str(replacement),
            stage=str(stage), data=str(data), version=health['version'], previous_version=health['version'],
            token=secrets.token_hex(24))
        transaction = stage / 'transaction.json'; transaction.write_text(json.dumps(payload))
        helper = subprocess.Popen([str(stage / 'helper.app/Contents/MacOS/LaoyuSync'), '--apply-update', str(transaction)],
            env=env, cwd=stage, start_new_session=True)
        wait_for(lambda: (stage / 'helper-ready.json').exists())
        close_marker(target).write_text('{"close":true}')
        old.wait(timeout=30)
        backup = wait_for(lambda: next(profile.glob('LaoyuSync.app.previous-*'), None))
        # A restored fixture must stay open until its own end-of-test close action.
        close_marker(backup).unlink(missing_ok=True)
        receipt = data / 'update-result.json'
        outcome = wait_for(lambda: json.loads(receipt.read_text()) if receipt.exists() else None, timeout=130)
        assert outcome['ok'] is not fault, outcome
        helper.wait(timeout=15)
        assert wait_for(lambda: api('/api/mydevice')['id']) == identity
        assert (data / 'identity-marker').read_text() == 'preserve-isolated-user-data'
        if not fault:
            assert json.loads((stage / 'healthy.json').read_text())['renderer_ready'] is True
            assert list((data / 'update-backups').glob('*.json'))
        result.update(ok=True, version=health['version'], renderer_and_engine_ack=True,
            window_visible=True, feedback_url_configured=True, pet_toggle=True,
            identity_preserved=True, user_data_preserved=True, outcome=outcome)
    finally:
        try:
            stop_bundle(target)
            old.wait(timeout=5)
        except Exception as error:
            result['cleanup_error'] = str(error)
        if helper and helper.poll() is None:
            helper.terminate(); helper.wait(timeout=15)
        result['clean_exit'] = not matching_pids(target)
        (profile.parent / ('rollback.json' if fault else 'success.json')).write_text(json.dumps(result, indent=2))
    assert result.get('ok') and result.get('clean_exit') and not result.get('cleanup_error'), result
    print(json.dumps({key: value for key, value in result.items() if key != 'outcome'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle')
    parser.add_argument('--profile', default='verification/mac-native')
    args = parser.parse_args()
    bundle, profile = Path(args.bundle).resolve(), Path(args.profile).resolve()
    scenario(bundle, profile / 'success')
    scenario(bundle, profile / 'rollback', fault=True)
