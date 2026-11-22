"""kamug logosu: Göktürk "k" harfi (dikey gövde, sola yükselen iki eğik kol).

Üretir: kamug/assets/logo.png (beyaz harf, saydam; arayüzde tema rengine boyanır) ve logo.ico
(açık gri yuvarlak kare üstünde koyu harf, 16-256 px). Logo değişirse bir kez çalıştırılır:
    python packaging/make_logo.py
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "kamug", "assets")

# Harf, yükseklik = 1 birim. Kollar soldan sağa aşağı iner, gövdeye bağlanır (tablodaki biçim).
W, T = 0.46, 0.135              # harf genişliği, çizgi kalınlığı
DROP = 0.17                     # kolun soldan gövdeye inişi
STEM_X = W - T


def _arm(y0, x1):
    s = DROP / W
    return [(0, y0), (x1, y0 + s * x1), (x1, y0 + s * x1 + T * 1.05), (0, y0 + T * 1.05)]


def glyph_polys():
    s = DROP / W
    stem = [(STEM_X, s * STEM_X), (W, DROP), (W, 1.0), (STEM_X, 1.0)]
    return [stem, _arm(0.0, W), _arm(0.335, STEM_X + 0.01)]


def draw_glyph(img, box, color):
    """box = (x, y, yükseklik) — harfin sol üst köşesi ve yüksekliği (piksel)."""
    x, y, h = box
    d = ImageDraw.Draw(img)
    for poly in glyph_polys():
        d.polygon([(x + px * h, y + py * h) for px, py in poly], fill=color)


def make_png(path, ss=8):
    w, h = 262, 306                              # eski Γ logosuyla aynı tuval (yerleşim değişmesin)
    big = Image.new("RGBA", (w * ss, h * ss), (255, 255, 255, 0))
    gh = (h - 60) * ss
    draw_glyph(big, ((w * ss - W * gh) / 2, 30 * ss, gh), (255, 255, 255, 255))
    big.resize((w, h), Image.LANCZOS).save(path)


def tile(size, ss=8):
    n = size * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    grad = Image.new("RGBA", (n, n))
    gd = ImageDraw.Draw(grad)
    for yy in range(n):                          # üstten alta açık griden biraz koyuya
        v = int(236 - (236 - 191) * yy / max(1, n - 1))
        gd.line([(0, yy), (n, yy)], fill=(v, v, v, 255))
    mask = Image.new("L", (n, n), 0)
    r = int(n * 0.19)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], r, fill=255)
    img.paste(grad, (0, 0), mask)
    ImageDraw.Draw(img).rounded_rectangle([ss // 2, ss // 2, n - 1 - ss // 2, n - 1 - ss // 2], r,
                                          outline=(150, 150, 150, 255), width=max(1, ss // 2))
    gh = n * (0.62 if size > 24 else 0.70)
    draw_glyph(img, ((n - W * gh) / 2, (n - gh) / 2, gh), (24, 24, 24, 255))
    return img.resize((size, size), Image.LANCZOS)


def make_ico(path):
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [tile(s) for s in sizes]
    imgs[-1].save(path, sizes=[(s, s) for s in sizes], append_images=imgs[:-1])


if __name__ == "__main__":
    make_png(os.path.join(ASSETS, "logo.png"))
    make_ico(os.path.join(ASSETS, "logo.ico"))
    print("ok")
