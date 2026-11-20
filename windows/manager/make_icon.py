from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 248, 248), radius=68, fill='#173d30')
draw.line([(68, 131), (108, 171), (187, 86)], fill='#c5f6d4', width=24, joint='curve')
image.save(Path(__file__).parent / 'resources/app.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
