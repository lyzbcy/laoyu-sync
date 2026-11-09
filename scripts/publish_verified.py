"""Publish exact successful CI packages on a runner, with full public readback.

Large transfers stay on the runner instead of consuming a developer's proxy quota.
The stable source manifest is deliberately updated separately after this succeeds.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from assemble_release import assemble, release_changes, __version__

REPO = 'lyzbcy/laoyu-sync'
ROOT = Path('release-assets')


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def release_for_tag(tag):
    # A newly created draft may have no Git tag yet, so /releases/tags is 404,
    # and the list API itself can lag a fresh create by seconds (0.3.14 hit
    # this: draft created, listing still empty, StopIteration). Retry briefly.
    for attempt in range(6):
        releases = json.loads(gh('api', f'repos/{REPO}/releases?per_page=100'))
        found = next((release for release in releases if release['tag_name'] == tag), None)
        if found:
            return found
        time.sleep(5)
    raise ValueError('Release not visible after create: ' + tag)


def validated_run(run_id, job):
    if not re.fullmatch(r'[0-9]+', run_id):
        raise ValueError('Invalid build run ID')
    run = json.loads(gh('api', f'repos/{REPO}/actions/runs/{run_id}'))
    if run['status'] != 'completed' or run['path'] != '.github/workflows/build.yml' or run['event'] != 'workflow_dispatch':
        raise ValueError('A completed package build is required')
    jobs = json.loads(gh('api', f'repos/{REPO}/actions/runs/{run_id}/jobs?filter=latest'))['jobs']
    matches = [entry for entry in jobs if entry['name'] == job]
    if len(matches) != 1 or matches[0]['conclusion'] != 'success':
        raise ValueError('Native build job did not succeed: ' + job)
    return run


def upstream_recipe(revision):
    # Only the network retry wrapper can differ across the two verified builds.
    source = subprocess.check_output(['git','show',revision + ':scripts/fetch_engine.py'])
    body = ast.parse(source).body
    return [ast.dump(node) for node in body if (
        isinstance(node, ast.FunctionDef) and node.name == 'main'
        or isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in ('VERSION', 'BASE') for target in node.targets))]


def validate():
    run_id = os.environ['BUILD_RUN_ID']
    mac_id = os.environ.get('MACOS_BUILD_RUN_ID') or run_id
    windows = validated_run(run_id, 'windows')
    macos = validated_run(mac_id, 'macos')
    if run_id == mac_id and windows['conclusion'] != 'success':
        raise ValueError('Combined build did not succeed')
    runtime_inputs = ['core','ui','LaoyuSync.spec','installer','assets','requirements.txt',
        'scripts/package.py','scripts/package_mac.py','scripts/prepare_feedback.py',
        'scripts/make_icon.py','scripts/prepare_resources.py','.github/workflows/build.yml']
    subprocess.run(['git','diff','--exit-code',windows['head_sha'],'--',
                    *runtime_inputs,'scripts/fetch_engine.py'], check=True)
    subprocess.run(['git','diff','--exit-code',macos['head_sha'],'--',*runtime_inputs], check=True)
    if upstream_recipe(macos['head_sha']) != upstream_recipe(windows['head_sha']):
        raise ValueError('Pinned upstream engine version or extraction differs')
    ROOT.mkdir(exist_ok=True)
    (ROOT/'build.json').write_text(json.dumps(dict(run_id=run_id, source=windows['head_sha'],
        macos_run_id=mac_id, macos_source=macos['head_sha'])))


def publish():
    build = json.loads((ROOT/'build.json').read_text())
    final = ROOT/'final'; final.mkdir(exist_ok=True)
    names = [f'laoyu-sync-{__version__}-{suffix}' for suffix in
             ('win-x64.zip','win-x64-setup.exe','macos-arm64.zip')]
    for name in names:
        matches = list(ROOT.glob('*/'+name))
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous artifact: '+name)
        shutil.copyfile(matches[0], final/name)
    win = json.loads((ROOT/'laoyu-sync-windows-native-evidence/result.json').read_text())
    mac_root = ROOT/'laoyu-sync-macos-native-evidence'
    if not (win.get('ok') and win.get('feedback_url_configured') and win.get('clean_exit')
            and win.get('ack', {}).get('version') == __version__):
        raise ValueError('Windows native gate not satisfied')
    for name in ('success','rollback','archive'):
        receipt = json.loads((mac_root/(name+'.json')).read_text())
        if (not receipt.get('ok') or receipt.get('version') != __version__
                or (name != 'archive' and not receipt.get('clean_exit'))):
            raise ValueError('Mac native gate not satisfied: '+name)
    assemble(final)
    notes = Path('release-notes.md')
    notes.write_text('\n'.join('- ' + item for item in release_changes()) + '\n\n'
        'Windows x64 / Mac Apple Silicon。没有自更新能力的旧版需要先手动安装。Windows 未代码签名，Mac 为临时签名且未公证。\n\n'
        f'Windows 构建：https://github.com/{REPO}/actions/runs/{build["run_id"]}\n'
        f'Mac 构建：https://github.com/{REPO}/actions/runs/{build["macos_run_id"]}\n', encoding='utf-8')
    tag = 'v'+__version__
    existing = subprocess.run(['gh','release','view',tag,'--repo',REPO,'--json','isDraft'],capture_output=True,text=True)
    if existing.returncode == 0:
        if not json.loads(existing.stdout)['isDraft']:
            raise ValueError('Published versions are immutable')
    else:
        gh('release','create',tag,'--repo',REPO,'--target',build['source'],
           '--title','捞鱼文件夹同步 '+__version__,'--notes-file',str(notes),'--draft')
    files = [final/name for name in names] + [final/f'SHA256SUMS-{__version__}.txt',final/'version.json']
    release = release_for_tag(tag)
    for file in files:
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        found = next((asset for asset in release['assets'] if asset['name']==file.name),None)
        if found:
            if found.get('digest') != 'sha256:'+digest:
                raise ValueError('Refusing to replace a release asset: '+file.name)
        else:
            gh('release','upload',tag,str(file),'--repo',REPO)
    draft_assets = {asset['name']: asset for asset in release_for_tag(tag)['assets']}
    for file in files:
        asset = draft_assets.get(file.name, {})
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if asset.get('digest') != 'sha256:' + digest or asset.get('size') != file.stat().st_size:
            raise ValueError('Draft asset differs from the verified build: ' + file.name)
    gh('release','edit',tag,'--repo',REPO,'--draft=false','--latest')
    release = release_for_tag(tag)
    evidence = dict(build=build,version=__version__,assets=[])
    for file in files:
        expected = hashlib.sha256(file.read_bytes()).hexdigest()
        asset = next(asset for asset in release['assets'] if asset['name']==file.name)
        actual = hashlib.sha256()
        with urllib.request.urlopen(asset['browser_download_url'],timeout=60) as response:
            for chunk in iter(lambda: response.read(1024*1024), b''):
                actual.update(chunk)
        if actual.hexdigest() != expected or asset.get('digest') != 'sha256:'+expected:
            raise ValueError('Public readback mismatch: '+file.name)
        evidence['assets'].append(dict(name=file.name,sha256=expected,size=asset['size'],url=asset['browser_download_url']))
    evidence['ok'] = True
    (ROOT/'public-readback.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))


if __name__ == '__main__':
    {'validate':validate,'publish':publish}[sys.argv[1]]()
