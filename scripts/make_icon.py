"""Repository-native app icon matching the desktop fish."""
from PIL import Image, ImageDraw
from pathlib import Path

root = Path(__file__).resolve().parent.parent
assets = root / 'assets'
assets.mkdir(exist_ok=True)
im = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((4, 4, 252, 252), 58, fill='#e8f6ef')
d.polygon([(87, 128), (32, 87), (44, 130), (32, 174)], fill='#177b67')
d.polygon([(96, 81), (128, 43), (158, 83)], fill='#177b67')
d.ellipse((66, 71, 221, 202), fill='#39ad92', outline='#177b67', width=5)
d.ellipse((79, 146, 209, 196), fill='#fafffc')
d.ellipse((153, 88, 200, 135), fill='white', outline='#163e34', width=3)
d.ellipse((168, 100, 188, 122), fill='#163e34')
d.ellipse((170, 102, 178, 110), fill='white')
d.arc((160, 137, 197, 169), 0, 160, fill='#163e34', width=4)
d.ellipse((192, 137, 211, 150), fill='#fac8d4')
im.save(assets / 'app.png')
im.resize((1024,1024)).save(assets / 'app.icns')
im.save(assets / 'app.ico', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
