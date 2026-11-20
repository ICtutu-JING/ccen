from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
image = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((80, 80, 944, 944), radius=272, fill='#183c34')
draw.line([(288, 544), (432, 688), (736, 368)], fill='#b5f3cb', width=96)
image.save(root / 'resources/app.icns')
