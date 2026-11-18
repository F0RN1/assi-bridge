"""Иконки приложения Assi — тонкая геометрическая «A» с выходом правой ноги за основу.

Только Pillow, без сети. Запуск: .venv\\Scripts\\python.exe make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BG = (8, 8, 9)
INK = (245, 246, 248)

OUT = Path(__file__).parent / "static"


def draw_mark(size: int, scale: float = 1.0) -> Image.Image:
    """Чёрный фон и контурная «A»: треугольник, правая нога выходит за основу."""
    img = Image.new("RGB", (size, size), BG)
    cx = size / 2

    # лёгкое свечение внутри знака
    glow = Image.new("RGB", (size, size), BG)
    gd = ImageDraw.Draw(glow)
    r = size * 0.26 * scale
    cy = size * 0.50
    for i in range(10, 0, -1):
        k = i / 10
        rr = r * (1 + k * 1.2)
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(14, 16, 20))
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.05))
    img = Image.blend(img, glow, 0.6)

    d = ImageDraw.Draw(img)
    w = max(2, int(size * 0.0155 * scale))
    ink = INK if scale > 0.9 else (245, 246, 248)

    s = size * scale
    top = size * 0.5 - s * 0.34
    bot = size * 0.5 + s * 0.30
    half = s * 0.235          # половина ширины основы

    apex = (cx, top)
    left = (cx - half, bot)
    right = (cx + half, bot)
    tail = (cx + half + s * 0.028, bot + s * 0.030)   # выход правой ноги за основу

    # левая нога, основа, правая нога с хвостом
    d.line([apex, left], fill=ink, width=w)
    d.line([left, right], fill=ink, width=w)
    d.line([apex, tail], fill=ink, width=w)

    # перекладина между ногами
    y = top + (bot - top) * 0.63
    k = (y - top) / (bot - top)
    w_at = half * k
    d.line([(cx - w_at, y), (cx + w_at, y)], fill=ink, width=w)

    # круглые окончания
    for p in (apex, left, right, tail):
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=ink)
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = draw_mark(1024)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    big.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    big.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    big.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png")
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    draw_mark(1024, scale=0.72).resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")
    print("готово:", ", ".join(sorted(p.name for p in OUT.glob("icon*.png"))))


if __name__ == "__main__":
    main()
