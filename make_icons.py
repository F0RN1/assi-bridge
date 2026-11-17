"""Генерация иконок PWA «Асси» без внешних сервисов (только Pillow)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "static"
S = 1024
BG = (17, 19, 24)
BLUE = (42, 109, 244)
CYAN = (86, 214, 255)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, c0, c1, diagonal=True):
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    for i in range(size):
        d.line([(0, i), (size, i)], fill=lerp(c0, c1, i / max(1, size - 1)))
    if diagonal:
        img = img.rotate(-35, resample=Image.BICUBIC, expand=False)
        img = img.resize((size, size))
    return img


def rounded_mask(size, radius, box=None):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    box = box or (0, 0, size - 1, size - 1)
    d.rounded_rectangle(box, radius=radius, fill=255)
    return m


def build() -> Image.Image:
    base = Image.new("RGBA", (S, S), BG + (255,))

    # мягкое голубое свечение в центре
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((S * 0.14, S * 0.14, S * 0.86, S * 0.86), fill=BLUE + (110,))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.11))
    base.alpha_composite(glow)

    # пузырь чата
    pad_x, pad_y = S * 0.20, S * 0.24
    bw, bh = S - pad_x * 2, S * 0.44
    box = (pad_x, pad_y, pad_x + bw, pad_y + bh)
    radius = bh * 0.34

    bubble = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = gradient(S, CYAN, BLUE).convert("RGBA")
    bubble.paste(grad, (0, 0), rounded_mask(S, int(radius), box))

    # хвостик пузыря (градиент тот же, что у пузыря)
    tail_mask = Image.new("L", (S, S), 0)
    tm = ImageDraw.Draw(tail_mask)
    x0, y1 = pad_x + bw * 0.30, box[3] - 8
    tm.polygon([(x0, y1 - 10), (x0 + bw * 0.24, y1 - 10), (x0 + bw * 0.05, y1 + bh * 0.34)], fill=255)
    tail = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tail.paste(grad, (0, 0), tail_mask)
    bubble.alpha_composite(tail.filter(ImageFilter.GaussianBlur(0.6)))

    # три точки внутри: читается как «печатает»
    bd = ImageDraw.Draw(bubble)
    r = bh * 0.085
    cy = (box[1] + box[3]) / 2
    cx = (box[0] + box[2]) / 2
    gap = bh * 0.26
    for k in (-1, 0, 1):
        x = cx + k * gap
        bd.ellipse((x - r, cy - r, x + r, cy + r), fill=BG + (235,))

    base.alpha_composite(bubble)

    # внешний тонкий контур
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((6, 6, S - 7, S - 7), radius=int(S * 0.22),
                        outline=(255, 255, 255, 26), width=3)

    # скругление для «обычной» иконки
    return base


def main():
    icon = build()
    plain = icon.copy()
    plain.putalpha(rounded_mask(S, int(S * 0.22)))

    plain.resize((512, 512), Image.LANCZOS).save(OUT / "icon-512.png")
    plain.resize((192, 192), Image.LANCZOS).save(OUT / "icon-192.png")
    plain.resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
    plain.resize((32, 32), Image.LANCZOS).save(OUT / "favicon.png")

    # maskable: иконка в безопасной зоне (внутренние 80%)
    m = Image.new("RGBA", (S, S), BG + (255,))
    inner = build().resize((int(S * 0.8), int(S * 0.8)), Image.LANCZOS)
    m.alpha_composite(inner, (int(S * 0.1), int(S * 0.1)))
    m.resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")

    (OUT / "icon.png").write_bytes(b"") if False else None
    plain.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    print("иконки готовы:", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
