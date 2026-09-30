"""Register this verified local candidate in the owner's launcher source checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--launcher', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
launcher = Path(args.launcher).resolve()
manifest = json.loads((root/'dist/version.json').read_text(encoding='utf-8'))
name = manifest['download_url'].rsplit('/',1)[1]
archive = root/'dist'/name
if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['sha256']:
    raise ValueError('Package hash does not match candidate metadata')
adapter = {'schemaVersion':1,'id':'laoyu-sync','name':'捞鱼同步小助手','version':manifest['version'],'platform':'win32','architecture':'x64','executable':'LaoyuSync.exe','category':'桌面效率','summary':'中文引导电脑间同步文件，桌面小鱼实时展示状态。','siteUrl':'https://github.com/lyzbcy/laoyu-sync','iconPath':'assets/app.ico','videoIds':[], 'package':{'type':'portable-zip','path':'dist/'+name,'url':manifest['download_url'],'sha256':manifest['sha256']}}
(root/'launcher-adapter.json').write_text(json.dumps(adapter,ensure_ascii=False,indent=2),encoding='utf-8')
catalog_file = launcher/'catalog/products.json'
catalog = json.loads(catalog_file.read_text(encoding='utf-8'))
product = {'id':adapter['id'],'name':adapter['name'],'summary':adapter['summary'],'category':adapter['category'],'siteUrl':adapter['siteUrl'],'stage':'内测版','icon':'folder','kind':'desktop','releaseRepo':'lyzbcy/laoyu-sync','assetName':name,'publishedVersion':manifest['version'],'fallbackRelease':{'version':manifest['version'],'url':manifest['download_url'],'sha256':manifest['sha256'],'name':name,'sizeBytes':archive.stat().st_size},'videos':[],'iconImage':'assets/products/laoyu-sync.png','supportedPlatforms':['win32']}
catalog['products'] = [p for p in catalog['products'] if p['id'] != adapter['id']] + [product]
catalog_file.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
shutil.copy2(root/'assets/app.png',launcher/'ui/assets/products/laoyu-sync.png')
print('Prepared launcher source registration; production client/catalog publication remains separate')
