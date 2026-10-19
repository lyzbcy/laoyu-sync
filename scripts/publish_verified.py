"""Publish exact successful CI packages on a runner, with full public readback.

Large transfers stay on the runner instead of consuming a developer's proxy quota.
The stable source manifest is deliberately updated separately after this succeeds.
"""
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

from assemble_release import assemble, __version__

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


def validate():
    run_id = os.environ['BUILD_RUN_ID']
    if not re.fullmatch(r'[0-9]+', run_id):
        raise ValueError('Invalid build run ID')
    run = json.loads(gh('api', f'repos/{REPO}/actions/runs/{run_id}'))
    if run['conclusion'] != 'success' or run['path'] != '.github/workflows/build.yml' or run['event'] != 'workflow_dispatch':
        raise ValueError('A successful package build is required')
    subprocess.run(['git','diff','--exit-code',run['head_sha'],'--','core','ui',
        'LaoyuSync.spec','installer','assets','requirements.txt','scripts/package.py',
        'scripts/package_mac.py','scripts/prepare_feedback.py'], check=True)
    ROOT.mkdir(exist_ok=True)
    (ROOT/'build.json').write_text(json.dumps(dict(run_id=run_id, source=run['head_sha'])))


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
    if not (win.get('ok') and win.get('feedback_url_configured') and win.get('clean_exit')):
        raise ValueError('Windows native gate not satisfied')
    for name in ('success','rollback','archive'):
        receipt = json.loads((mac_root/(name+'.json')).read_text())
        if not receipt.get('ok') or (name != 'archive' and not receipt.get('clean_exit')):
            raise ValueError('Mac native gate not satisfied: '+name)
    assemble(final)
    notes = Path('release-notes.md')
    notes.write_text('同步直连一键自检：引擎归属、本地代理端口、系统层接管、转发痕迹与系统代理五项本地旁证，分级结论附处理指引，不宣称已验证直连。\n'
        '外部引擎一键接管：经引擎自身接口优雅退出并由小助手按直连偏好重启，不强杀、不自动触发；设置页三态状态条常驻显示直连应用情况。\n\n'
        'Windows x64 / Mac Apple Silicon。Mac旧版需先手动替换一次；Windows未代码签名，Mac为临时签名且未公证。\n\n'
        f'原始构建：https://github.com/{REPO}/actions/runs/{build["run_id"]}\n',encoding='utf-8')
    tag = 'v'+__version__
    existing = subprocess.run(['gh','release','view',tag,'--repo',REPO,'--json','isDraft'],capture_output=True,text=True)
    if existing.returncode == 0:
        if not json.loads(existing.stdout)['isDraft']:
            raise ValueError('Published versions are immutable')
    else:
        gh('release','create',tag,'--repo',REPO,'--target',build['source'],
           '--title','捞鱼同步小助手 '+__version__,'--notes-file',str(notes),'--draft')
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
