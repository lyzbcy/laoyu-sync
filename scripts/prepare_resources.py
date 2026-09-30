"""Prepare version resources and preserve dependency license texts in the bundle."""
import importlib.metadata
from pathlib import Path
import re
import shutil
import sys

root = Path(__file__).resolve().parent.parent
ver = re.search(r'__version__ = "([^"]+)"', (root/'core/version.py').read_text(encoding='utf-8')).group(1)
numbers = tuple(map(int, ver.split('.'))) + (0,)
fields = {'CompanyName':'捞鱼工作室','FileDescription':'捞鱼同步小助手','FileVersion':ver,'InternalName':'LaoyuSync','OriginalFilename':'LaoyuSync.exe','ProductName':'Laoyu Sync','ProductVersion':ver}
strings = ',\n'.join(f'StringStruct({key!r}, {value!r})' for key,value in fields.items())
(root/'assets/version_info.txt').write_text(f'''VSVersionInfo(ffi=FixedFileInfo(filevers={numbers!r},prodvers={numbers!r},mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)), kids=[StringFileInfo([StringTable('080404b0',[{strings}])]),VarFileInfo([VarStruct('Translation',[2052,1200])])])''', encoding='utf-8')
licenses = root/'licenses'
licenses.mkdir(exist_ok=True)
python_license = Path(sys.base_prefix)/'LICENSE.txt'
if python_license.is_file():
    shutil.copy2(python_license, licenses/'Python.txt')
for package in ['pywebview','qrcode','Pillow','pyinstaller','pythonnet','clr-loader','cffi','pycparser','bottle','typing_extensions','proxy_tools']:
    try:
        distribution = importlib.metadata.distribution(package)
    except importlib.metadata.PackageNotFoundError:
        continue
    for file in distribution.files or []:
        if re.match(r'(?i)^(license|copying|notice)', Path(file).name):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                destination = licenses/package/Path(file).name
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(source,destination)
print('Prepared version',ver,'and dependency license texts')
