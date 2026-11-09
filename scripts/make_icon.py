"""Derive window, launcher and installer art from the approved logo."""
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parent.parent
assets = root / 'assets'
with Image.open(assets / 'app-approved.png') as source:
    icon = source.convert('RGBA')
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(assets / 'app.png')
    icon.resize((1024, 1024), Image.Resampling.LANCZOS).save(assets / 'app.icns')
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        assets / 'app.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    icon.resize((96, 96), Image.Resampling.LANCZOS).save(root / 'ui/assets/brand.png')

    # Inno Setup uses opaque BMPs. Match the installer's mint palette.
    header = Image.new('RGB', (55, 55), '#eef2e9')
    mark = icon.resize((51, 51), Image.Resampling.LANCZOS)
    header.paste(mark, (2, 2), mark)
    header.save(root / 'installer/header.bmp')

with Image.open(root / 'ui/assets/stickers/第12弹-挥手.png') as source:
    art = source.convert('RGBA')
    art.thumbnail((150, 165), Image.Resampling.LANCZOS)
    panel = Image.new('RGB', (164, 314), '#e3efe2')
    panel.paste(art, ((164 - art.width) // 2, 86), art)
    panel.save(root / 'installer/welcome.bmp')
