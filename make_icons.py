"""Иконки приложения Assi — геометрическая «A» тонкой линией.

Только Pillow, без сети. Запуск: .venv\\Scripts\\python.exe make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BG = (11, 13, 16)
INK = (242, 246, 255)
GLOW = (86, 214, 255)
OUT = Path(__file__).parent / "static"


def draw_mark(size: int, scale: float = 1.0) -> Image.Image:
    """Тёмный фон, мягкое свечение и тонкая треугольная «A» по центру."""
    img = Image.new("RGB", (size, size), BG)
    cx = cy = size / 2

    # свечение
    glow = Image.new("RGB", (size, size), BG)
    gd = ImageDraw.Draw(glow)
    r = size * 0.30 * scale
    for i in range(9, 0, -1):
        k = i / 9
        rr = r * (1 + k * 1.6)
        col = tuple(int(BG[j] + (GLOW[j] - BG[j]) * (0.10 * (1 - k))) for j in range(3))
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col)
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.06))
    img = Image.blend(img, glow, 0.75)

    d = ImageDraw.Draw(img)
    w = max(2, int(size * 0.019 * scale))

    top = cy - size * 0.28 * scale
    bot = cy + size * 0.26 * scale
    half = size * 0.27 * scale
    apex = (cx, top)
    left = (cx - half, bot)
    right = (cx + half, bot)

    for a, b in ((apex, left), (apex, right), (left, right)):
        d.line([a, b], fill=INK, width=w, joint="curve")

    # перекладина «A» — на 0.66 высоты, ровно между боковыми линиями
    y = top + (bot - top) * 0.66
    w_at = half * ((y - top) / (bot - top))
    d.line([(cx - w_at * 0.94, y), (cx + w_at * 0.94, y)], fill=INK, width=w)

    # круглые окончания штрихов
    for p in (apex, left, right):
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=INK)
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = draw_mark(1024)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    big.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    big.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    big.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png")
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    # maskable: знак меньше, чтобы не обрезался круглой маской
    draw_mark(1024, scale=0.72).resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")
    print("готово:", ", ".join(sorted(p.name for p in OUT.glob("icon*.png"))))


if __name__ == "__main__":
    main()
