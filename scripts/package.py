"""Create final immutable Windows ZIP and real hash metadata."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'core'))
from version import __version__

bundle = root / 'dist/LaoyuSync'
for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
    (bundle / name).write_bytes((root / name).read_bytes())
(bundle / '使用说明.txt').write_text('捞鱼同步小助手 ' + __version__ + '\n请完整解压到可写文件夹，再打开 LaoyuSync.exe。无需 Python。\n两边交换设备 ID，接受配对；创建项目共享给对方，对方选择保存位置接收。\n修改和删除会同步；新项目远端变更默认留存旧文件30天，同步不是备份。\n只退出助手会停止它自己启动的引擎；已有独立运行的 Syncthing 不会被停止。\n配置和日志保存在本机用户数据目录 LaoyuSync，同步配置由 Syncthing 管理。\n无遥测；诊断日志可能含路径，请检查后分享。当前 Windows 包未签名。\n', encoding='utf-8')
name = f'laoyu-sync-{__version__}-win-x64.zip'
archive = root / 'dist' / name
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for file in sorted(bundle.rglob('*')):
        if file.is_file():
            z.write(file, file.relative_to(bundle).as_posix())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
url = f'https://github.com/lyzbcy/laoyu-sync/releases/download/v{__version__}/{name}'
manifest = {'version': __version__, 'notes': '完整安装与便携版、可靠状态、共享设置、小鱼与安全更新', 'download_url': url, 'sha256': digest, 'sizeBytes': archive.stat().st_size}
(root / 'dist/version.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
adapter = {'schemaVersion': 1, 'id': 'laoyu-sync', 'name': '捞鱼同步小助手', 'version': __version__, 'platform':'win32', 'architecture':'x64', 'executable':'LaoyuSync.exe', 'category':'桌面效率', 'summary':'中文引导电脑间同步文件，桌面小鱼实时展示状态。', 'siteUrl':'https://github.com/lyzbcy/laoyu-sync', 'iconPath':'assets/app.ico', 'videoIds':[], 'package':{'type':'portable-zip','path':'dist/' + name,'url':url,'sha256':digest}}
(root / 'launcher-adapter.json').write_text(json.dumps(adapter, ensure_ascii=False, indent=2), encoding='utf-8')
print(name, archive.stat().st_size, digest)
