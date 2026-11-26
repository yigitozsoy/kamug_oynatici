"""kamug için hızlı uçtan uca duman testi.

Çalıştırma:   python tests/smoke_test.py          (çekirdek + arayüz; pencere ekran dışında, sessiz)
              python tests/smoke_test.py --show   (pencere görünür)
              python tests/smoke_test.py --no-gui (yalnızca çekirdek)

Gerçek tercihlere dokunmaz: LOCALAPPDATA geçici bir klasöre yönlendirilir. Test medyası ffmpeg ile
geçici klasörde üretilir ve sonunda silinir.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

TMP = tempfile.mkdtemp(prefix="kamug_test_")
os.environ["LOCALAPPDATA"] = os.path.join(TMP, "appdata")
os.environ["KAMUG_SILENT"] = "1"                     # VLC sesi hoparlöre gitmesin
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np                                   # noqa: E402
from PIL import Image, ImageDraw                     # noqa: E402
from PyQt6.QtCore import QTimer                      # noqa: E402
from PyQt6.QtWidgets import QApplication             # noqa: E402

app = QApplication(sys.argv[:1])

from kamug import image_io, thumbs, watermark  # noqa: E402
from kamug.bgremove import remove_background   # noqa: E402
from kamug.config import prefs                 # noqa: E402
from kamug.formats import kind_of              # noqa: E402
from kamug.image_editor import DEFAULT_STATE, render  # noqa: E402
from kamug.library import Library              # noqa: E402

prefs.data["single_instance"] = False
MEDIA = os.path.join(TMP, "media")
os.makedirs(MEDIA)
results = []


def check(name):
    def deco(fn):
        t0 = time.perf_counter()
        try:
            fn()
            results.append((True, name, int((time.perf_counter() - t0) * 1000), ""))
        except Exception:
            results.append((False, name, 0, traceback.format_exc(limit=3)))
        return fn
    return deco


def ff(*a):
    subprocess.run([thumbs.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *a], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def M(name):
    return os.path.join(MEDIA, name)


# ------------------------------------------------------------------ test medyası
@check("ffmpeg bulundu ve medya üretildi")
def _make_media():
    assert thumbs.FFMPEG and os.path.exists(thumbs.FFMPEG), thumbs.FFMPEG
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
       "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", M("video.mp4"))
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "3", "-c:v", "mpeg4", M("video.avi"))
    ff("-f", "lavfi", "-i", "sine=frequency=330", "-f", "lavfi", "-i", "testsrc=size=300x300", "-t", "5",
       "-map", "0:a", "-map", "1:v", "-frames:v", "1", "-c:a", "libmp3lame", "-c:v", "mjpeg",
       "-disposition:v", "attached_pic", "-metadata", "title=Deneme Şarkı", "-metadata", "artist=Sanatçı",
       M("song.mp3"))
    ff("-f", "lavfi", "-i", "sine=frequency=550", "-t", "3", "-c:a", "flac", M("tone.flac"))
    ff("-f", "lavfi", "-i", "sine=frequency=660", "-t", "8", "-c:a", "aac", M("audio_only.mp4"))
    open(M("video.srt"), "w", encoding="utf-8").write("1\n00:00:00,500 --> 00:00:04,000\nMerhaba ş ğ ı\n")
    im = Image.new("RGB", (800, 500), (255, 255, 255))
    ImageDraw.Draw(im).ellipse([250, 100, 550, 400], fill=(220, 30, 60))
    ImageDraw.Draw(im).rectangle([380, 230, 420, 270], fill=(255, 255, 255))   # içteki beyaz delik
    im.save(M("white_bg.jpg"), quality=95)
    im.save(M("image.png"))
    im.save(M("image.webp"))
    im.save(M("image.bmp"))
    im.save(M("image.tiff"))
    im.save(M("image.ico"), sizes=[(16, 16), (48, 48), (256, 256)])
    frames = [Image.new("RGB", (120, 90), (i * 20, 40, 90)) for i in range(6)]
    frames[0].save(M("anim.gif"), save_all=True, append_images=frames[1:], duration=80, loop=0)
    import pillow_heif
    pillow_heif.register_heif_opener()
    im.save(M("image.heic"), quality=70)
    im.save(M("image.avif"), quality=70)
    import imagecodecs
    open(M("image.jxl"), "wb").write(imagecodecs.jpegxl_encode(np.asarray(im)))
    open(M("vector.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                                     '<circle cx="32" cy="32" r="30" fill="#3ea6ff"/></svg>')


def _write_models():
    """Küçük bir küpü desteklenen tüm 3D biçimlerinde yazar (yalnızca numpy)."""
    import json
    import struct
    import zipfile
    V = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=np.float32)
    F = np.array([[0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6], [0, 1, 5], [0, 5, 4],
                  [2, 6, 7], [2, 7, 3], [0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5]], dtype=np.int64)
    tri = V[F]
    with open(M("cube.stl"), "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(F)))
        for t_ in tri:
            f.write(struct.pack("<12fH", 0, 0, 0, *t_.reshape(-1), 0))
    with open(M("cube_ascii.stl"), "w") as f:
        f.write("solid c\n")
        for t_ in tri:
            f.write("facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {a} {b} {c}\n" for a, b, c in t_)
                    + "endloop\nendfacet\n")
        f.write("endsolid c\n")
    open(M("cube.mtl"), "w").write("newmtl red\nKd 0.9 0.1 0.1\n")
    with open(M("cube.obj"), "w") as f:
        f.write("mtllib cube.mtl\nusemtl red\n" + "".join(f"v {a} {b} {c}\n" for a, b, c in V))
        f.write("".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in F))
    with open(M("cube.ply"), "wb") as f:
        f.write(f"ply\nformat binary_little_endian 1.0\nelement vertex {len(V)}\nproperty float x\n"
                f"property float y\nproperty float z\nelement face {len(F)}\n"
                f"property list uchar int vertex_indices\nend_header\n".encode())
        f.write(V.tobytes())
        for a, b, c in F:
            f.write(struct.pack("<B3i", 3, a, b, c))
    with open(M("cube.off"), "w") as f:
        f.write(f"OFF\n{len(V)} {len(F)} 0\n" + "".join(f"{a} {b} {c}\n" for a, b, c in V)
                + "".join(f"3 {a} {b} {c}\n" for a, b, c in F))
    idx = F.astype(np.uint16).tobytes()
    binb = idx + b"\0" * (-len(idx) % 4) + V.tobytes()
    js = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
          "nodes": [{"mesh": 0, "translation": [5, 0, 0]}],
          "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0, "material": 0}]}],
          "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.1, 0.4, 0.9, 1]}}],
          "buffers": [{"byteLength": len(binb)}],
          "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(idx)},
                          {"buffer": 0, "byteOffset": len(idx) + (-len(idx) % 4), "byteLength": V.nbytes}],
          "accessors": [{"bufferView": 0, "componentType": 5123, "count": F.size, "type": "SCALAR"},
                        {"bufferView": 1, "componentType": 5126, "count": len(V), "type": "VEC3",
                         "min": [0, 0, 0], "max": [1, 1, 1]}]}
    jb = json.dumps(js).encode()
    jb += b" " * (-len(jb) % 4)
    with open(M("cube.glb"), "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(jb) + 8 + len(binb)))
        f.write(struct.pack("<I4s", len(jb), b"JSON") + jb)
        f.write(struct.pack("<I4s", len(binb), b"BIN\0") + binb)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/'
           'core/2015/02"><resources><object id="1" type="model"><mesh><vertices>'
           + "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in V) + "</vertices><triangles>"
           + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in F)
           + '</triangles></mesh></object></resources><build><item objectid="1"/></build></model>')
    with zipfile.ZipFile(M("cube.3mf"), "w") as z:
        z.writestr("3D/3dmodel.model", xml)


MODEL_FILES = ("cube.stl", "cube_ascii.stl", "cube.obj", "cube.ply", "cube.off", "cube.glb", "cube.3mf")


@check("3D modeller üretildi")
def _models_written():
    _write_models()


# ------------------------------------------------------------------ çekirdek
@check("dosya türleri tanınıyor")
def _formats():
    exp = {"video.mp4": "video", "video.avi": "video", "song.mp3": "audio", "tone.flac": "audio",
           "image.jxl": "image", "image.heic": "image", "image.ico": "image", "anim.gif": "image",
           "vector.svg": "image", "video.srt": None, "cube.stl": "model", "x.GLB": "model", "x.gltf": "model",
           "cube.3mf": "model", "cube.obj": "model", "cube.ply": "model"}
    for f, k in exp.items():
        assert kind_of(f) == k, (f, kind_of(f))


@check("tüm görsel biçimleri açılıyor")
def _images():
    for f in ("white_bg.jpg", "image.png", "image.webp", "image.bmp", "image.tiff", "image.ico", "anim.gif",
              "image.heic", "image.avif", "image.jxl", "vector.svg"):
        li = image_io.load_image(M(f))
        assert li is not None and not li.first.isNull(), f
    assert image_io.load_image(M("anim.gif")).animated


@check("3D biçimleri açılıyor (stl/obj/ply/off/glb/3mf) + küçük resim")
def _models():
    from kamug.model_io import load_model, render_preview
    for f in MODEL_FILES:
        m = load_model(M(f))
        assert m.triangles == 12, (f, m.triangles)
        assert np.allclose(m.size, 1.0, atol=1e-4), (f, m.size)
    assert load_model(M("cube.stl")).vertices == 8
    assert load_model(M("cube.obj")).parts[0].color[:3] == (0.9, 0.1, 0.1)
    assert abs(load_model(M("cube.glb")).bmin[0] - 5) < 1e-5     # düğüm dönüşümü uygulandı
    img = render_preview(load_model(M("cube.glb")), 160, 90)
    assert img.width() == 160 and img.pixelColor(80, 45) != img.pixelColor(2, 2), "küçük resim boş"


@check("3D dönüştürme (stl/obj/3mf/glb/ply) ve ölçüler")
def _model_export():
    from kamug.model_io import load_model, export_model, dims_text, dims_values, EXPORT_FORMATS

    def mm(model):   # fiziksel boy (mm): birimler farklı olsa da aynı kalmalı
        w, d, h, unit = dims_values(model)
        k = {"mm": 1, "cm": 10, "m": 1000}[unit]
        return np.array([w, d, h]) * k
    out = os.path.join(TMP, "model_export")   # medya klasörünü kirletmesin
    os.makedirs(out, exist_ok=True)
    assert dims_text(load_model(M("cube.stl")), "tr") == "1 × 1 × 1 mm"
    assert dims_text(load_model(M("cube.glb")), "en") == "1 × 1 × 1 m"    # glTF birimi metre
    for src in ("cube.stl", "cube.glb", "cube.obj"):
        m = load_model(M(src))
        for _label, ext in EXPORT_FORMATS:
            dst = os.path.join(out, src.replace(".", "_") + ext)
            export_model(m, dst)
            m2 = load_model(dst)
            assert m2.triangles == 12, (src, ext, m2.triangles)
            assert np.allclose(mm(m2), mm(m), rtol=1e-4), (src, ext, dims_text(m2), dims_text(m))
    # hacim / alan / kapalılık: 1 mm küp
    from kamug.model_io import model_stats
    st = model_stats(load_model(M("cube.stl")))
    assert abs(st["volume"] - 1) < 1e-6 and abs(st["area"] - 6) < 1e-6 and st["closed"] is True, st
    st = model_stats(load_model(M("cube.glb")))
    assert abs(st["volume"] - 1e9) < 1 and st["closed"] is True, st   # 1 m³ = 1e9 mm³
    from kamug.model_io import Model, Part
    open_box = Model([Part(load_model(M("cube.stl")).parts[0].pos[:-3])], "STL")   # bir üçgeni eksik
    assert model_stats(open_box)["closed"] is False
    # renk korunuyor (OBJ'deki kırmızı malzeme → GLB)
    m2 = load_model(os.path.join(out, "cube_obj.glb"))
    assert np.allclose(m2.parts[0].color[:3], (0.9, 0.1, 0.1), atol=1e-3), m2.parts[0].color


@check("3MF hızlı okuma: boya öznitelikleri, üçgen renkleri, önekli ad alanı")
def _3mf_variants():
    import zipfile
    from kamug.model_io import load_model
    base = load_model(M("cube.3mf"))
    V = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    F = [(0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4),
         (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5)]
    ns = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
    verts = "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in V)

    def write(name, tris, pre="", res=""):
        xml = (f'<?xml version="1.0"?><{pre}model {ns.replace("xmlns", "xmlns:m") if pre else ns}><{pre}resources>{res}'
               f'<{pre}object id="1" type="model"><{pre}mesh><{pre}vertices>'
               + verts.replace("<vertex", f"<{pre}vertex") + f"</{pre}vertices><{pre}triangles>" + tris
               + f'</{pre}triangles></{pre}mesh></{pre}object></{pre}resources><{pre}build><{pre}item objectid="1"/>'
               f'</{pre}build></{pre}model>')
        with zipfile.ZipFile(M(name), "w") as z:
            z.writestr("3D/3dmodel.model", xml)
        return load_model(M(name))
    # Bambu: yalnızca bazı üçgenlerde paint_color
    m = write("paint.3mf", "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"' + (' paint_color="4"' if i % 3 == 0 else "")
                                   + "/>" for i, (a, b, c) in enumerate(F)))
    assert m.triangles == 12 and np.allclose(m.parts[0].pos, base.parts[0].pos), "paint_color"
    # üçgen başına renk (p1)
    res = '<basematerials id="5"><base name="r" displaycolor="#FF0000"/><base name="b" displaycolor="#0000FF"/></basematerials>'
    m = write("p1.3mf", "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}" pid="5" p1="{i % 2}"/>'
                                for i, (a, b, c) in enumerate(F)), res=res)
    assert m.triangles == 12 and m.parts[0].col is not None, "p1"
    assert np.allclose(m.parts[0].col[0], (1, 0, 0)) and np.allclose(m.parts[0].col[3], (0, 0, 1)), m.parts[0].col[:6]
    # ad alanı önekli yazım (m:mesh)
    m = write("prefix.3mf", "".join(f'<m:triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in F), pre="m:")
    assert m.triangles == 12 and np.allclose(m.size, 1.0), "önek"
    for f in ("paint.3mf", "p1.3mf", "prefix.3mf"):
        os.remove(M(f))


@check("3D küçük resim sınırları (dosya sayısı / MB)")
def _model_thumb_limits():
    from kamug.library import MediaItem
    from kamug import layout_prefs as lp
    svc = thumbs.ThumbnailService()
    svc.ensure = lambda it: None
    items = []
    for i in range(30):
        it = MediaItem.__new__(MediaItem)
        it.path, it.kind, it.size, it.mtime = f"C:/x/m{i:02}.stl", "model", 1024 * 1024, 0
        items.append(it)
    items[16].size = 30 * 1024 * 1024
    svc.request(items, items[15])
    skipped = [i for i, it in enumerate(items) if svc._skip_model(it)]
    assert len(skipped) == 11 and 16 in skipped and 15 not in skipped, skipped   # 20 yakın + 1 büyük dosya
    assert 0 in skipped and 29 in skipped, skipped
    lp.prefs.data["model_thumb_count"], lp.prefs.data["model_thumb_mb"] = 0, 0
    svc.request(items, items[15])
    assert not any(svc._skip_model(it) for it in items)
    del lp.prefs.data["model_thumb_count"], lp.prefs.data["model_thumb_mb"]


@check("STEP / IGES (gmsh varsa): açılış, tam hacim, Türkçe yol")
def _step():
    from kamug.model_io import cad_available, load_model, model_stats, dims_text
    if not cad_available():
        print("  (gmsh kurulu değil, STEP testi atlandı)")
        return
    # 10 × 20 × 30 mm kutu + r=5 silindir; ayrı süreçte üretilir (gmsh tek örnekli, uygulamanınkini bozmasın)
    step = os.path.join(MEDIA, "küp şekil.step")
    raw = os.path.join(TMP, "cad.step")
    code = ("import gmsh,sys; gmsh.initialize(interruptible=False); gmsh.option.setNumber('General.Terminal',0);"
            "gmsh.model.occ.addBox(0,0,0,10,20,30); gmsh.model.occ.addCylinder(50,0,0,0,0,10,5);"
            "gmsh.model.occ.synchronize(); gmsh.write(sys.argv[1]); gmsh.finalize()")
    subprocess.run([sys.executable, "-c", code, raw], check=True, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    shutil.copy(raw, step)
    m = load_model(step)
    assert m.fmt == "STEP" and m.triangles > 12, (m.fmt, m.triangles)
    st = model_stats(m)
    exp = 10 * 20 * 30 + np.pi * 25 * 10
    assert abs(st["volume"] - exp) < 1e-3 * exp and st["closed"] is True, st
    assert dims_text(m, "tr").endswith("mm"), dims_text(m, "tr")
    m2 = load_model(step)   # önbellekten: aynı sonuç, dönüşüm iki kez uygulanmamalı
    assert np.allclose(m2.size, m.size), (m2.size, m.size)


@check("görsel dönüştürme (png/jpg/webp/bmp/tiff/ico)")
def _convert():
    src = image_io.open_pil(M("white_bg.jpg"))
    for ext in ("png", "jpg", "webp", "bmp", "tiff", "ico"):
        out = os.path.join(TMP, "conv." + ext)
        image_io.save_pil(src, out)
        assert os.path.getsize(out) > 0, ext
        Image.open(out).load()
    ico = Image.open(os.path.join(TMP, "conv.ico"))
    assert ico.size[0] == ico.size[1], ico.size          # kare simge


@check("arka plan kaldırma (beyaz zemin, iç delik korunur)")
def _bgremove():
    src = image_io.open_pil(M("white_bg.jpg"))
    out = remove_background(src, None, 20, True, 6)
    a = np.asarray(out.getchannel("A"))
    assert a[5, 5] == 0 and a[-5, -5] == 0, "köşeler saydam değil"
    assert a[150, 400] == 255, "nesne silinmiş"
    assert a[250, 400] == 255, "nesnenin içindeki beyaz delik silinmiş (yalnızca kenar modu)"
    out2 = remove_background(src, (255, 255, 255), 20, False, 6)
    assert np.asarray(out2.getchannel("A"))[250, 400] == 0
    st = dict(DEFAULT_STATE, bg={"color": None, "tol": 20, "edge": True, "feather": 6})
    r = render(src, st, final=True)
    assert r.mode == "RGBA"
    image_io.save_pil(r, os.path.join(TMP, "nobg.ico"))
    ico = Image.open(os.path.join(TMP, "nobg.ico")).convert("RGBA")
    assert ico.getpixel((0, 0))[3] == 0, "ICO saydam değil"


@check("ffmpeg: süre, çözünürlük, kare, kapak, etiket, dalga formu")
def _ffmpeg():
    err = thumbs.probe(M("video.mp4"))
    assert 5500 <= thumbs.parse_duration(err) <= 6500
    assert thumbs.parse_resolution(err) == (640, 360)
    assert not thumbs.grab_frame(M("video.mp4"), 2000, 320).isNull()
    assert not thumbs.grab_frame(M("video.mp4"), 4000, 320, accurate=True).isNull()
    assert not thumbs.extract_cover(M("song.mp3")).isNull()
    tg = thumbs.media_tags(M("song.mp3"))
    assert tg["tags"].get("title") == "Deneme Şarkı", tg
    assert tg["info"].get("hz"), tg
    assert not thumbs.waveform(M("tone.flac"), 400, 60).isNull()


@check("klasör tarama ve sıralama")
def _library():
    lib = Library()
    lib.open_path(M("video.mp4"))
    assert lib.current is not None and lib.current.name == "video.mp4"
    assert not any(i.path.endswith(".srt") for i in lib.all_items)
    for s in Library.SORTS:
        lib.set_sort(s)
        assert len(lib.items) == len(lib.all_items), s


@check("filigran çizimi")
def _watermark():
    prefs.data.update(wm_text_on=True, wm_text="gamma", wm_pos="br")
    img = watermark.render(640, 360)
    prefs.data.update(wm_text_on=False)
    arr = img.constBits().asstring(img.sizeInBytes())
    assert any(arr[3::4]), "yazı çizilmedi"


@check("çeviri anahtarları tanımlı")
def _i18n():
    import glob
    import re
    from kamug.i18n import S
    used = set()
    for f in glob.glob(os.path.join(ROOT, "kamug", "*.py")):
        used |= set(re.findall(r'\bt\(\s*"([a-z0-9_]+[a-z0-9])"', open(f, encoding="utf-8").read()))
    missing = sorted(k for k in used - set(S) if not k.endswith("_") and k != "anahtar")
    assert not missing, missing


@check("transkript: canlı satır, altyazıdan, paragraf, SRT; OCR an seçimi; yazıt notu")
def _transcript_core():
    import numpy as np
    from kamug import transcript as tr, screen_text as st, yazit_export as dx
    assert tr.parse_live("[00:01:02.500 --> 00:01:04.000]   Merhaba") == (62500, 64000, "Merhaba")
    assert tr.parse_live("whisper_init: ...") is None
    segs = tr.parse_subtitle_text("1\n00:00:01,000 --> 00:00:02,500\n<i>Selam</i>\n\n"
                                  "2\n00:00:03,000 --> 00:00:04,000\n[MÜZİK]\n\n"
                                  "3\n00:00:09,000 --> 00:00:10,000\nNasılsın?\n")
    assert [x["t"] for x in segs] == ["Selam", "Nasılsın?"], segs
    assert len(tr.paragraphs(segs)) == 2                 # 5 sn duraklama → yeni paragraf
    assert "00:00:01,000 --> 00:00:02,500" in tr.to_srt(segs)
    assert tr.fmt_ts(3725000) == "1:02:05"
    a = np.zeros(st.SW * st.SH, np.int16)
    b = a.copy()
    b[:200] = 255                                        # küçük bir yazı değişimi
    frames = [a, a, a, b, b, b, b]
    assert st.pick_moments(frames) == [0.0, 3.0], st.pick_moments(frames)
    assert st.dedupe([(0, "Başlık", "a"), (1, "Başlık", "b"), (2, "Başlık\nmadde 1", "c"),
                      (5, "Bambaşka slayt", "d")]) == [(0, "Başlık\nmadde 1", "c"), (5, "Bambaşka slayt", "d")]
    note = dx.build_note(r"C:\v\ders.mp4", {"speech": {"segments": segs}}, "k")
    assert note["format"] == "delta-note" and note["version"] == 2
    links = [i["ln"] for i in note["items"] if "ln" in i]
    assert links and links[0] == {"kamug": r"C:\v\ders.mp4", "t": 1.0}, links


@check("gelişmiş okuma: çıktı temizliği, formül gösterimi, sayfa gruplama, metin dışa aktarma")
def _vlm_core():
    import numpy as np
    from kamug import vlm_ocr, screen_text as st, transcript as tr
    raw = "```markdown\n**Soru**\nz = \\frac{x-\\mu}{\\sigma} \\\\\nTekrar\nTekrar\nTekrar\n```"
    c = vlm_ocr.clean(raw)
    assert c == "**Soru**\n$z = \\frac{x-\\mu}{\\sigma}$\nTekrar", repr(c)
    assert vlm_ocr.to_display(c) == "Soru\nz = (x-μ)/σ\nTekrar", vlm_ocr.to_display(c)
    assert vlm_ocr.to_display("$x^2 \\leq \\sqrt{16}$, $e^{-x}$") == "x² ≤ √(16), e^(-x)"
    assert "-ngl" not in vlm_ocr.command("a.jpg")          # 4 GB kartta çöküyordu
    a = np.zeros(st.SW * st.SH, np.int16)
    b, c2, d = a.copy(), a.copy(), a.copy()
    b[:300] = 255                                        # sayfa yazılmaya başladı
    c2[:600] = 255                                       # aynı sayfaya eklendi
    d[5000:5600] = 255                                   # yeni sayfa
    frames = [a, b, c2, d]
    assert st.group_pages(frames, [1.0, 2.0, 3.0]) == [(1.0, 2.0), (3.0, 3.0)], st.group_pages(frames, [1.0, 2.0, 3.0])
    txt = tr.frames_txt([{"s": 1000, "t": "$a$"}, {"s": 61000, "t": ""}])
    assert txt == "[0:01]\n$a$\n", repr(txt)


@check("konuşmacı ayırma: iki farklı ses ayrılır, tek ses bölünmez")
def _speakers():
    import wave
    import numpy as np
    from kamug import speakers
    rng = np.random.default_rng(3)
    t = np.arange(int(2.5 * 16000)) / 16000

    def voice(f0, bright, k):
        f = f0 * (1 + 0.03 * np.sin(2 * np.pi * (0.7 + k * 0.13) * t))
        ph = 2 * np.pi * np.cumsum(f) / 16000
        x = sum((bright ** h) * np.sin(h * ph) for h in range(1, 25))
        env = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * (2.5 + k * 0.3) * t))
        return x * env / 8 + rng.normal(0, 0.01, len(t))
    parts, segs, pos = [], [], 0
    for i in range(6):
        a = voice(110 + 4 * i, 0.55, i) if i % 2 == 0 else voice(230 + 5 * i, 0.85, i)
        parts += [a, np.zeros(8000)]
        segs.append({"s": int(pos / 16), "e": int((pos + len(a)) / 16), "t": str(i)})
        pos += len(a) + 8000
    path = os.path.join(TMP, "spk.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(np.concatenate(parts), -1, 1) * 30000).astype(np.int16).tobytes())
    assert speakers.diarize(path, segs) == 2 and [x["spk"] for x in segs] == [1, 2, 1, 2, 1, 2], segs
    one = [dict(x) for i, x in enumerate(segs) if i % 2 == 0]
    assert speakers.diarize(path, one) == 1, [x["spk"] for x in one]


SERIES = os.path.join(MEDIA, "dizi")
_OP = ("aevalsrc='0.25*sin(2*PI*(300+100*floor(mod(t*2,8)))*t)+0.12*sin(2*PI*(800+60*floor(mod(t*3,5)))*t)"
       "+0.08*sin(2*PI*(1500+200*floor(mod(t*1.5,6)))*t)':s=22050:d=40")
SERIES_COLD = [0, 17.5, 33.2]


def _make_episode(path, cold, seed):
    """Soğuk açılış (gürültü) + aynı 40 sn opening + bölüm (farklı gürültü)."""
    parts = ([f"anoisesrc=d={cold}:c=pink:seed={seed}:a=0.3:r=22050"] if cold else []) + \
        [_OP, f"anoisesrc=d={100 - cold}:c=brown:seed={seed + 5}:a=0.4:r=22050"]
    args = []
    for p in parts:
        args += ["-f", "lavfi", "-i", p]
    n = len(parts)
    fc = "".join(f"[{k}:a]aformat=channel_layouts=mono[a{k}];" for k in range(n))
    fc += "".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    ff(*args, "-f", "lavfi", "-i", "color=c=0x203040:s=160x90:d=140:r=5", "-filter_complex", fc,
       "-map", "[out]", "-map", f"{n}:v", "-c:a", "aac", "-b:a", "64k", "-c:v", "libx264", "-preset", "ultrafast",
       "-shortest", path)


@check("dizi: ad çözümleme, sezon/bölüm, altyazı eşleme, ad önerisi")
def _series_parse():
    from kamug import series as ser
    cases = {
        "Attack on Titan S03e13 1080p WEB x264-GRP.mkv": ("episode", "Attack on Titan", 3, 13),
        "attack.on.titan.3x14.720p.mkv": ("episode", "attack on titan", 3, 14),
        "[SubsPlease] Frieren - 07 (1080p) [ABCD1234].mkv": ("episode", "Frieren", 1, 7),
        "Breaking Bad 2. Sezon 5. Bölüm.mp4": ("episode", "Breaking Bad", 2, 5),
        "The Office S02E01E02.avi": ("episode", "The Office", 2, 1),
        "Inception.2010.1080p.BluRay.x264.mkv": ("movie", "Inception", None, None),
    }
    for name, (kind, title, s, e) in cases.items():
        p = ser.parse(name)
        assert p is not None and p.kind == kind, (name, p and p.kind)
        assert p.title.lower() == title.lower(), (name, p.title)
        if kind == "episode":
            assert (p.season, p.episode) == (s, e), (name, p.season, p.episode)
    assert ser.parse("The Office S02E01E02.avi").episode2 == 2
    assert ser.parse("Inception.2010.1080p.BluRay.x264.mkv").year == 2010
    os.makedirs(SERIES, exist_ok=True)
    for i, c in enumerate(SERIES_COLD):
        _make_episode(os.path.join(SERIES, f"test.show.s01e{i + 1:02d}.720p.WEB.x264.mp4"), c, i * 7 + 1)
    for i in range(3):   # altyazı adları videoyla aynı değil, numaradan eşlenmeli
        with open(os.path.join(SERIES, f"TestShow_1x{i + 1:02d}.tr.srt"), "w", encoding="utf-8") as f:
            f.write(f"1\n00:00:01,000 --> 00:00:04,000\nBölüm {i + 1} şğüıöç\n")
    vids = sorted(os.path.join(SERIES, n) for n in os.listdir(SERIES) if n.endswith(".mp4"))
    s = ser.series_for(vids[1], vids)
    assert s is not None and len(s.episodes) == 3, s
    subs = ser.match_subtitles(s, ser.list_subtitles(SERIES))
    assert len(subs) == 3 and all(f"1x{i + 1:02d}" in os.path.basename(subs[v]) for i, v in enumerate(vids)), subs
    plan = ser.rename_plan(s, "Test Show", "dash")
    assert [os.path.basename(n) for _, n in plan][0] == "Test Show - S01E01.mp4", plan
    assert ser.needs_cleanup(s, "dash")


@check("dizi: intro bulma (farklı soğuk açılış süreleri) ve altyazı gömme")
def _series_intro():
    from kamug import intro, series as ser
    vids = sorted(os.path.join(SERIES, n) for n in os.listdir(SERIES) if n.endswith(".mp4"))
    ref, res = intro.detect(vids[:2])
    assert ref, "referans yok"
    _, res2 = intro.detect(vids[2:], ref=ref)
    res.update(res2)
    for v, c in zip(vids, SERIES_COLD):
        r = res.get(v)
        assert r, (os.path.basename(v), "intro bulunamadı")
        assert abs(r[0] / 1000 - c) < 1.5 and abs(r[1] / 1000 - (c + 40)) < 1.5, (os.path.basename(v), c, r)
    # Farklı ses: intro olmamalı
    ff("-f", "lavfi", "-i", "anoisesrc=d=60:c=white:seed=99:a=0.3", "-c:a", "aac", M("noise.m4a"))
    _, neg = intro.detect([M("noise.m4a")], ref=ref)
    assert not neg.get(M("noise.m4a")), neg
    # Gömme: yeniden kodlamadan mkv, altyazı izi var ve varsayılan
    out = os.path.join(TMP, "embed.mkv")
    sub = os.path.join(SERIES, "TestShow_1x01.tr.srt")
    r = subprocess.run(ser.embed_command(thumbs.FFMPEG, vids[0], sub, out), capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert r.returncode == 0 and os.path.getsize(out) > 0, r.stderr[-300:]
    probe = subprocess.run([thumbs.FFMPEG, "-hide_banner", "-i", out], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stderr
    assert "Subtitle" in probe and "(tur)" in probe and "(default)" in probe.split("Subtitle")[0][-200:] + \
        probe.split("Subtitle")[1][:200], probe[-800:]


# ------------------------------------------------------------------ arayüz
def gui_tests(done):
    from kamug.theme import theme
    theme.apply()
    from kamug.window import MainWindow
    from kamug import dialogs
    w = MainWindow([M("video.mp4")])
    hidden = "--show" not in sys.argv
    if hidden:       # varsayılan: pencere ekran dışında, odak çalmadan (kullanıcıyı rahatsız etmesin)
        from PyQt6.QtCore import Qt as _Qt
        w.setAttribute(_Qt.WidgetAttribute.WA_ShowWithoutActivating)
        w.move(-30000, -30000)
    w.show()
    steps = []

    def step(delay, name):
        def deco(fn):
            steps.append((delay, name, fn))
            return fn
        return deco

    state = {}

    @step(2500, "video oynatılıyor")
    def _():
        state["hwnd"] = int(w.winId())
        assert w.engine is not None, "VLC motoru yok"
        assert w.engine.is_playing(), "oynatılmıyor"
        assert w.engine.get_length() > 5000

    @step(10, "ileri sarma ve duraklatma")
    def _():
        w.engine.set_time(3000)
        w.toggle_play()

    @step(1000, "duraklatıldı / döngü modları")
    def _():
        assert not w.engine.is_playing(), "duraklatılamadı"
        w.cycle_loop()
        w.cycle_loop()
        w.cycle_loop()

    @step(10, "videodan görsele geçiş (<1 sn)")
    def _():
        t0 = time.perf_counter()
        w.play_item(w.lib.find(M("white_bg.jpg"), w.lib.all_items))
        ms = (time.perf_counter() - t0) * 1000
        assert ms < 1000, f"{ms:.0f} ms"

    @step(1200, "görsel gösteriliyor")
    def _():
        assert w.current.name == "white_bg.jpg"

    @step(10, "karışık klasörde sıradaki medya (tür fark etmez) ve kenar okları")
    def _():
        seq = w.lib._sequence()
        i = next(k for k, it in enumerate(seq) if it is w.current)
        state["img_back"] = w.current
        w.overlay.show_controls()
        w._sync_image_arrows(1.0)
        assert w._img_arrows["prev"].isVisible() == (i > 0), "sol ok"
        assert w._img_arrows["next"].isVisible() == (i < len(seq) - 1), "sağ ok"
        if i > 0:
            w._img_arrows["prev"].clicked.emit()
            assert w.current is seq[i - 1], (w.current.name, seq[i - 1].name)
            w.play_next()
            assert w.current is seq[i], w.current.name

    @step(1200, "görsele geri dönüldü")
    def _():
        if w.current is not state["img_back"]:
            w.play_item(state["img_back"])
        assert w.current.name == "white_bg.jpg"

    @step(10, "görsel düzenleyici açılıyor")
    def _():
        w._open_image_editor()
        assert w._edit_panel is not None, "düzenleyici açılmadı"

    @step(1500, "görsel düzenleyici: damlalıkla arka plan kaldırma")
    def _():
        from PyQt6.QtCore import QPointF
        p = w._edit_panel
        assert p.proxy is not None, "görsel yüklenmedi"
        p._bg_pick()
        assert getattr(w.viewer, "pick_mode", False)
        w.viewer.picked.emit(QPointF(3, 3))               # köşedeki beyaz piksel
        assert p.state["bg"] and tuple(p.state["bg"]["color"]) == (255, 255, 255), p.state["bg"]
        assert p._target_ext() == ".png", p._target_ext()   # jpg saydamlık için png olur
        p._save(os.path.join(TMP, "editor_out.png"))

    @step(2000, "düzenleyici çıktısı saydam PNG")
    def _():
        out = Image.open(os.path.join(TMP, "editor_out.png"))
        assert out.mode == "RGBA" and out.getpixel((2, 2))[3] == 0
        p = w._edit_panel
        p.state = dict(DEFAULT_STATE)
        p.history.clear()
        w._close_image_editor()

    @step(10, "düzenleyici: kırpma açıkken üzerine kaydet")
    def _():
        from kamug import image_editor
        from PyQt6.QtCore import QRectF
        from PyQt6.QtWidgets import QMessageBox
        w._open_image_editor()
        p = w._edit_panel
        t0 = time.time()
        while p.proxy is None and time.time() - t0 < 5:
            app.processEvents()
        p._start_crop()
        iw, ih = w.viewer._img_size()
        w.viewer.crop = QRectF(0, 0, iw / 2, ih)            # çerçeve açık, Enter'a basılmadan kaydet
        orig = image_editor.QMessageBox.question
        image_editor.QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes
        try:
            p.save_overwrite()
        finally:
            image_editor.QMessageBox.question = orig

    @step(2000, "kaydettikten sonra kırpma çerçevesi kalmadı")
    def _():
        assert not w.viewer.crop_mode, "kırpma çerçevesi hâlâ açık"
        im = Image.open(M("white_bg.jpg"))
        assert im.size == (400, 500), im.size              # açık kalan kırpma da uygulandı
        assert w._edit_panel is None, "düzenleyici kapanmadı"
        assert tuple(w.viewer._img_size()) == (400, 500), w.viewer._img_size()   # yeni resim gösteriliyor
        assert (w.current.width, w.current.height) == (400, 500), "listedeki çözünürlük eski"
        assert w.current.size == os.path.getsize(M("white_bg.jpg")), "listedeki dosya boyutu eski"

    @step(10, "yazı tipi yedekleri: Japonca, Göktürk, Arapça, Hintçe")
    def _():
        from PyQt6.QtGui import QTextLayout, QFont
        from kamug.theme import install_font_fallbacks
        install_font_fallbacks()
        for s in ("日本語のテキスト", "\U00010C34\U00010C07\U00010C2F", "العربية", "हिन्दी", "한국어"):
            lay = QTextLayout(s, QFont("Segoe UI Variable Text"))
            lay.beginLayout()
            lay.createLine()
            lay.endLayout()
            assert all(g != 0 for r in lay.glyphRuns() for g in r.glyphIndexes()), f"çizilemeyen harf: {s}"

    @step(10, "hızlı dönüştürme: ICO")
    def _():
        w.quick_convert(w.current, ".ico")

    @step(1500, "ICO dosyası oluştu")
    def _():
        assert os.path.exists(M("white_bg.ico"))

    @step(10, "saydam görselin zemin rengi (sağ tık)")
    def _():
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QImage, QColor
        img = QImage(40, 40, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        w.viewer.set_image(img)
        assert w.viewer.has_alpha()
        m = QMenu()
        w._add_alpha_bg_menu(m)
        acts = [a for a in m.actions()[0].menu().actions() if a.text()]
        assert acts[0].isChecked(), "varsayılan dama değil"
        acts[1].trigger()                                   # siyah
        assert prefs.get("image_alpha_bg") == "#000000" and w.viewer.alpha_bg == "#000000"
        g = w.viewer.grab().toImage()
        assert g.pixelColor(g.width() // 2, g.height() // 2).name() == "#000000"
        acts[0].trigger()
        assert w.viewer.alpha_bg == "checker"
        w._load_image(w.current)

    @step(10, "tercihler penceresi tüm kategoriler")
    def _():
        d = dialogs.PreferencesDialog(w)
        d.show()
        for i in range(d.nav.count()):
            d.nav.setCurrentRow(i)
            QApplication.processEvents()
        d.reject()

    @step(10, "tema değişimi")
    def _():
        theme.apply("light")
        theme.apply("dark")

    @step(10, "ses dosyası ve etiketler")
    def _():
        w.play_item(w.lib.find(M("song.mp3"), w.lib.all_items))

    @step(3000, "ses oynatılıyor")
    def _():
        assert w.engine.is_playing()

    @step(10, "3D model açılıyor")
    def _():
        w.play_item(w.lib.find(M("cube.glb"), w.lib.all_items))
        assert w.stack.currentIndex() == 4, w.stack.currentIndex()

    @step(1500, "3D model çiziliyor (OpenGL)")
    def _():
        v = w.viewer3d
        assert v is not None and v.model is not None, "model yüklenmedi"
        img = v.image()
        assert v._gl is not None, "OpenGL yok: " + v._gl_error
        assert v._gpu, "GPU'ya yüklenmedi"
        c = img.pixelColor(img.width() // 2, img.height() // 2)
        assert c != img.pixelColor(3, 3), "model görünmüyor"
        w.toggle_slideshow()
        assert v.autorotate
        w._fit_toggle()
        w._rotate_clicked()
        v.set_wireframe(True)
        v.image()
        w.toggle_slideshow()
        assert not v.autorotate

    @step(10, "3D: ölçü kutusu ve saydam PNG")
    def _():
        v = w.viewer3d
        v.set_wireframe(False)
        plain = v.image()
        v.set_dims(True)
        with_dims = v.image()
        assert plain.size() == with_dims.size()
        assert plain != with_dims, "ölçü kutusu çizilmedi"
        tr = v.image(transparent=True)
        assert tr.hasAlphaChannel() and tr.pixelColor(0, 0).alpha() == 0, "arka plan saydam değil"
        assert tr.pixelColor(tr.width() // 2, tr.height() // 2).alpha() > 200, "model yok"
        v.set_dims(False)

    @step(10, "3D: 1-9 kısayolları ve kesit")
    def _():
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import QEvent, Qt
        v = w.viewer3d
        plain = v.image()

        def key(k, mods=Qt.KeyboardModifier.NoModifier):
            w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, mods))
        key(Qt.Key.Key_2)
        assert v.section == "y", v.section
        cut = v.image()
        assert cut != plain, "kesit çizilmedi"
        key(Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
        assert abs(v.section_pos - 0.48) < 1e-6, v.section_pos
        for _ in range(3):
            key(Qt.Key.Key_2)
        assert v.section is None
        key(Qt.Key.Key_1)
        assert v._face == 1
        key(Qt.Key.Key_4)
        assert v.wireframe
        key(Qt.Key.Key_4)
        key(Qt.Key.Key_9)
        assert v.pitch == 90.0
        key(Qt.Key.Key_0)
        assert v.pitch == v.DEF_PITCH

    @step(10, "3D: sonraki model ve bilgi")
    def _():
        cur = w.current
        w.play_next()
        assert w.current is not cur and w.current.is_model, w.current.name
        d = dialogs.MediaInfoDialog(w.current, w)
        d.show()
        d.reject()

    @step(1200, "3D modelden videoya dönüş")
    def _():
        w.play_item(w.lib.find(M("video.mp4"), w.lib.all_items))
        assert w.stack.currentIndex() == 1 and not w.viewer3d.autorotate

    @step(2500, "3D'den sonra video görüntüsü var, pencere yeniden oluşmadı")
    def _():
        assert int(w.winId()) == state["hwnd"], "ana pencere yeniden oluşturuldu (3D görüntüleyici)"
        assert w.engine.is_playing() and w.engine.has_video(), "görüntü yok (yalnızca ses)"
        assert w.stack.currentIndex() == 1, w.stack.currentIndex()

    @step(10, "yalnızca ses içeren mp4")
    def _():
        w.play_item(w.lib.find(M("audio_only.mp4"), w.lib.all_items))

    @step(3500, "yalnızca ses içeren mp4 müzik görünümünde")
    def _():
        assert w.stack.currentIndex() == 2, w.stack.currentIndex()

    @step(10, "video düzenleyici açılıyor")
    def _():
        from kamug.video_editor import VideoEditorDialog
        d = VideoEditorDialog(w.lib.find(M("video.mp4"), w.lib.all_items), w)
        d.show()
        QApplication.processEvents()
        args = d.build_args()
        assert args, "ffmpeg argümanları boş"
        d.reject()

    def ep(i):
        return sorted(os.path.join(SERIES, n) for n in os.listdir(SERIES) if n.endswith(".mp4"))[i]

    @step(10, "dizi bölümü açılıyor")
    def _():
        from kamug import series as ser
        ser.store.data.clear()
        prefs.data["intro_auto"] = True
        prefs.data["series_subs"] = True
        w.open_paths([ep(1)])

    @step(3500, "dizi algılandı, altyazı açıldı, intro bulundu")
    def _():
        assert w._series is not None and len(w._series.episodes) == 3, w._series
        assert w.info._series_mode == "series", w.info._series_mode
        assert w.info.buttons["series"].isVisible(), "Dizi düğmesi görünmüyor"
        names = " ".join(n for _, n in w.engine.sub_tracks())
        assert len(w.engine.sub_tracks()) >= 2, names   # "Devre dışı" + eklenen
        assert w._intro, "intro bulunamadı"
        a, b = w._intro
        assert abs(a - 17500) < 1500 and abs(b - 57500) < 1500, w._intro
        w.engine.set_time(25000)

    @step(900, "intro sırasında \"İntroyu atla\" düğmesi sağ altta")
    def _():
        o = w.overlay
        assert o.btn_skip.isVisible(), "atla düğmesi görünmüyor"
        g = o.btn_skip.geometry()
        assert g.right() > o.width() * 0.7 and g.bottom() > o.height() * 0.6, g
        o.btn_skip.click()

    @step(900, "intro atlandı, düğme gizlendi")
    def _():
        assert w.engine.get_time() >= 55000, w.engine.get_time()
        assert not w.overlay.btn_skip.isVisible()

    @step(10, "zaman çubuğuna tıklama tek kez atlar (aradaki an tekrar oynamaz)")
    def _():
        calls = []
        orig = w.engine.set_time
        w.engine.set_time = lambda ms: (calls.append(ms), orig(ms))
        try:
            w._last_seek = 0.0
            w._on_seek(30000, False)     # basma
            w._on_seek(30000, True)      # bırakma (aynı nokta)
            assert calls == [30000], calls
            w._last_seek = 0.0
            w._on_seek(40000, False)
            w._on_seek(60000, True)      # sürükleyip başka yerde bırakma: son konuma atlamalı
            assert calls[-1] == 60000, calls
        finally:
            w.engine.set_time = orig

    @step(10, "basılı tutunca hızlandırma (ayarlı hız, her yer / sağ yarı)")
    def _():
        prefs.data["hold_rate"], prefs.data["hold_area"] = 3.0, "anywhere"
        w._on_hold(True, 0.2)
        assert abs(w.engine.rate() - 3.0) < 0.01, w.engine.rate()
        w._on_hold(False, 0.2)
        assert abs(w.engine.rate() - 1.0) < 0.01, w.engine.rate()
        prefs.data["hold_area"] = "right"
        w._on_hold(True, 0.2)
        assert abs(w.engine.rate() - 1.0) < 0.01, "sol yarıda hızlanmamalı"
        w._on_hold(False, 0.2)
        prefs.data.pop("hold_rate")
        prefs.data.pop("hold_area")

    @step(10, "linkten indir: link tanıma, komut, sahte yt-dlp ile indir ve aç")
    def _():
        from kamug import ytdl
        from kamug.ytdl_dialog import DownloadDialog
        assert ytdl.find_url("bak: youtu.be/dQw4w9WgXcQ?t=3") == "https://youtu.be/dQw4w9WgXcQ?t=3"
        assert ytdl.find_url("https://www.youtube.com/shorts/abcdefghijk")
        assert ytdl.find_url("site: https://example.com/v/1.mp4 bak") == "https://example.com/v/1.mp4"
        assert ytdl.find_url("link yok") is None
        # fotoğraf gönderileri (gallery-dl)
        assert ytdl.photo_first("https://www.tiktok.com/@a/photo/123")
        assert ytdl.photo_first("https://www.reddit.com/gallery/abc") and ytdl.photo_first("https://pin.it/x")
        assert not ytdl.photo_first("https://www.instagram.com/p/abc/")
        assert ytdl.photo_candidate("ERROR: [instagram] abc: There is no video in this post")
        assert not ytdl.photo_candidate("ERROR: Sign in to confirm your age")
        gcmd = ytdl.gallery_command("https://x.com/a/status/1", TMP, "firefox")
        assert gcmd[-1] == "https://x.com/a/status/1" and "--cookies-from-browser" in gcmd
        cmd = ytdl.download_command("https://youtu.be/x", TMP, "720", thumbs.FFMPEG)
        assert "res:720,ext:mp4:m4a" in cmd and cmd[-1] == "https://youtu.be/x" and "--no-playlist" in cmd
        assert ytdl.format_args("720", "video")[:2] == ["-f", "bv/bv*"]
        assert "-x" in ytdl.download_command("https://youtu.be/x", TMP, "best", content="audio")
        assert ytdl.parse_line("kamug-progress 50 NA 200 1000") == ("progress", 0.25, 1000.0, None, None)
        pl = "https://www.youtube.com/playlist?list=PLabc"
        assert ytdl.playlist_only(pl) and not ytdl.playlist_only("https://youtube.com/watch?v=abcdefg&list=PLabc")
        ic = ytdl.info_command(pl, flat=True, playlist=True)
        assert "--flat-playlist" in ic and "--yes-playlist" in ic and "--simulate" in ic
        e = ytdl.parse_entry("kamug-entry 3\tabc\t57\t14990413\tListem\t25\thttps://x/v3\tBaşlık")
        assert (e["index"], e["size"], e["playlist"], e["title"]) == (3, 14990413.0, "Listem", "Başlık"), e
        assert ytdl.safe_name('a:b/c?') == "a_b_c_"
        stub = os.path.join(TMP, "fake_ytdlp.py")
        with open(stub, "w", encoding="utf-8") as f:
            f.write(
                "import os, shutil, sys, time\n"
                "sys.stdout.reconfigure(encoding='utf-8')\n"
                "a = sys.argv[1:]\n"
                "if '--info' in a:\n"
                "    if '--list' in a:\n"
                "        for i in (1, 2, 3):\n"
                "            size = 'NA' if '--flat' in a else str(i * 10 * 1048576)\n"
                "            print(f'kamug-entry {i}\\tid{i}\\t{60 * i}\\t{size}\\tListem\\t3\\thttps://x/v{i}\\tVideo {i}', flush=True)\n"
                "    else:\n"
                "        print('kamug-entry 0\\tabc\\t57\\t15000000\\tNA\\tNA\\thttps://x/v\\tBenim videom', flush=True)\n"
                "    sys.exit(0)\n"
                "out = a[0]\n"
                "if '--imp' not in a:\n"     # ilk deneme: bot koruması -> tarayıcı gibi tekrar denenmeli
                "    print('ERROR: [generic] Got HTTP Error 403 caused by Cloudflare anti-bot challenge; try again "
                "with  --extractor-args \"generic:impersonate\"', flush=True); sys.exit(1)\n"
                "for i in range(1, 5):\n"
                "    print(f'kamug-progress {i * 25} 100 NA 2048', flush=True); time.sleep(0.05)\n"
                "print('[Merger] Merging', flush=True)\n"
                "os.makedirs(os.path.dirname(out), exist_ok=True)\n"
                f"shutil.copy({M('video.mp4')!r}, out)\n"
                "print('kamug-file ' + out, flush=True)\n")
        imp = ytdl.download_command("https://example.com/v", TMP, "best", impersonate=True)
        assert "--impersonate" in imp and "generic:impersonate" in imp
        assert ytdl.error_hint("ERROR: [generic] Got HTTP Error 403 caused by Cloudflare anti-bot") == "yt_blocked"
        ytdl.installed = lambda: True
        ytdl.needs_update_check = lambda: False
        ytdl.info_command = lambda url, flat=False, playlist=False, **kw: \
            [sys.executable, stub, "--info"] + (["--flat"] if flat else []) + (["--list"] if playlist else [])

        def fake_dl(url, folder, q, ff=None, **kw):
            name = (kw.get("name") or "Benim videom [abc]").replace("%(title).120B [%(id)s]", "Video " + url[-1])
            imp = kw.get("impersonate") or kw.get("name")      # listedeki videolar korumasız
            return [sys.executable, stub, os.path.join(folder, name + ".mp4")] + (["--imp"] if imp else [])
        ytdl.download_command = fake_dl
        prefs.data["yt_enabled"] = True
        prefs.data["yt_folder"] = os.path.join(TMP, "indirilen")
        w.apply_personalization()
        assert w.home.btn_link.isVisibleTo(w.home), "ana sayfada Linkten aç yok"
        d = DownloadDialog(w, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        d.show()
        assert d.btn_go.isEnabled() and not d.list_mode
        d._start()
        state["yt_dlg"] = d

    @step(2500, "linkten indirilen video açıldı (bilgi: ad, süre, boyut)")
    def _():
        assert w.current is not None and w.current.name == "Benim videom [abc].mp4", w.current and w.current.name
        assert not state["yt_dlg"].isVisible()

    @step(10, "oynatma listesi: bilgi alınıyor")
    def _():
        from kamug.ytdl_dialog import DownloadDialog
        d = DownloadDialog(w, "https://www.youtube.com/playlist?list=PLabc")
        d.show()
        state["yt_list"] = d

    @step(2000, "oynatma listesi: adet, boyutlar, seçim; aynı anda indir")
    def _():
        d = state["yt_list"]
        assert d.list_mode and d.tb.rowCount() == 3, (d.list_mode, d.tb.rowCount())
        assert [e["size"] for e in d.entries] == [10485760.0, 20971520.0, 31457280.0], [e["size"] for e in d.entries]
        assert "3 / 3" in d.lbl_sum.text() and "60.0 MB" in d.lbl_sum.text(), d.lbl_sum.text()
        d._cell_clicked(1, d.COL_TITLE)            # 2. videoyu çıkar
        assert "2 / 3" in d.lbl_sum.text() and "40.0 MB" in d.lbl_sum.text(), d.lbl_sum.text()
        d.cmb_mode.setCurrentIndex(1)              # aynı anda
        d._start()
        assert d.downloading and d.parallel == 3

    @step(2500, "oynatma listesi: yalnızca seçilenler indi, ilki açıldı")
    def _():
        folder = os.path.join(TMP, "indirilen", "Listem")
        names = sorted(os.listdir(folder))
        assert names == ["001 - Video 1.mp4", "003 - Video 3.mp4"], names
        assert w.current.name == "001 - Video 1.mp4", w.current.name
        assert not state["yt_list"].isVisible()
        prefs.data["yt_enabled"] = False
        w.apply_personalization()

    @step(10, "transkript paneli: varsayılan kapalı, açılınca düğme ve panel")
    def _():
        from kamug import transcript as tr
        assert not w.info.buttons["transcript"].isVisibleTo(w.info), "transkript düğmesi varsayılanda görünmemeli"
        prefs.data["transcript_enabled"] = True
        w.apply_personalization()
        assert w.info.buttons["transcript"].isVisibleTo(w.info)
        key = tr.file_key(w.current.path)
        tr.save(key, {"speech": {"segments": [{"s": 0, "e": 1500, "t": "Birinci cümle"},
                                              {"s": 2000, "e": 3000, "t": "İkinci cümle burada"},
                                              {"s": 4000, "e": 5000, "t": "Üçüncü"}]}})
        w._on_info_action("transcript")
        assert w.right.isVisible() and w.right.currentWidget() is w._tr_panel
        p = w._tr_panel
        assert p.model.rowCount() == 3, p.model.rowCount()
        p.set_time(2500)
        assert p.model.current == 1
        p._row_clicked(p.model.index(2))
        state["tr_seek"] = 4000

    @step(600, "transkript: satıra tıklayınca o ana gitti; arama süzer")
    def _():
        p = w._tr_panel
        assert abs(w.engine.get_time() - state["tr_seek"]) < 1500, w.engine.get_time()
        p.search.setText("ikinci")
        assert p.model.rowCount() == 1
        p.search.clear()
        assert p.model.rowCount() == 3

    @step(10, "transkript: sahte whisper ile çıkar (canlı satırlar, kayıt)")
    def _():
        from kamug import transcript as tr
        p = w._tr_panel
        tr.remove(p.key)
        p.data = {}
        stub = os.path.join(TMP, "fake_whisper.py")
        with open(stub, "w", encoding="utf-8") as f:
            f.write("import json, sys, time\n"
                    "sys.stdout.reconfigure(encoding='utf-8')\n"
                    "a = sys.argv[1:]\n"
                    "out = a[a.index('-of') + 1]\n"
                    "segs = [(0, 1500, 'Merhaba'), (2000, 3500, 'gamma')]\n"
                    "for s, e, t in segs:\n"
                    "    print(f'[00:00:0{s // 1000}.000 --> 00:00:0{e // 1000}.500]  {t}', flush=True)\n"
                    "    time.sleep(0.05)\n"
                    "json.dump({'result': {'language': 'tr'}, 'transcription': [{'offsets': {'from': s, 'to': e},"
                    " 'text': ' ' + t} for s, e, t in segs]}, open(out + '.json', 'w', encoding='utf-8'))\n")
        tr.missing_downloads = lambda key=None: []
        tr.whisper_command = lambda wav, out, **kw: [sys.executable, stub, "-of", out] + (["-tr"] if kw.get("translate") else [])
        p.start_speech()
        assert p._job() is not None

    @step(3000, "transkript çıkarıldı ve kaydedildi; --at ile aynı videoda o ana gider")
    def _():
        from kamug import transcript as tr
        p = w._tr_panel
        assert p._job() is None, "iş bitmedi"
        assert [r["t"] for r in p.model.rows] == ["Merhaba", "gamma"], p.model.rows
        assert tr.load(p.key)["speech"]["lang"] == "tr"
        p.start_speech(translate=True)            # İngilizce çeviri sekmesi
        state["tr_en"] = True

    @step(2500, "transkript: çeviri sekmesi; --at ile aynı videoda o ana gider")
    def _():
        p = w._tr_panel
        assert p._running("speech_en") is None, "çeviri bitmedi"
        assert p.chip_en.isVisibleTo(p) and p.tab == "speech_en" and p.model.rowCount() == 2
        p.set_tab("speech")
        w.open_paths([w.current.path], 2500)
        assert abs(w.engine.get_time() - 2500) < 1200, w.engine.get_time()
        w.close_transcript()
        assert w.right.currentWidget() is w.sidebar
        prefs.data["transcript_enabled"] = False
        w.apply_personalization()

    @step(10, "dizi penceresine dönüş")
    def _():
        w.open_paths([ep(1)])

    @step(1500, "dizi penceresi: toplu yeniden adlandırma (açık bölüm dahil, altyazılar da)")
    def _():
        from kamug.series_dialog import SeriesDialog
        d = SeriesDialog(w, w.current)
        d.show()
        QApplication.processEvents()
        assert d.tabs.count() == 3 and d.tb_rename.rowCount() == 3
        d.ed_title.setText("Test Show")
        d._apply_rename()
        names = sorted(os.listdir(SERIES))
        assert "Test Show - S01E02.mp4" in names and "Test Show - S01E02.tr.srt" in names, names
        assert w.current.name == "Test Show - S01E02.mp4", w.current.name
        assert d.tb_rename.rowCount() == 0
        assert d.tb_subs.rowCount() == 3 and d.tb_intro.rowCount() == 3
        d.reject()
        state["dlg_ok"] = True

    @step(1500, "yeniden adlandırılan bölüm oynuyor, intro hatırlandı")
    def _():
        assert w.engine.is_playing(), "oynatılmıyor"
        assert w._intro and abs(w._intro[1] - 57500) < 1500, w._intro

    @step(10, "geliştirici konsolu: Shift+\" modu açar, \" açar / kapatır, yazı alanında yazılır, komutlar, geçmiş, tamamlama")
    def _():
        from PyQt6.QtCore import Qt as _Qt, QEvent
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QLineEdit
        from kamug import cli
        con, keys = w.console, w.console_keys

        def key(shift=False, scan=41, k=_Qt.Key.Key_QuoteDbl, text='"'):
            mods = _Qt.KeyboardModifier.ShiftModifier if shift else _Qt.KeyboardModifier.NoModifier
            return QKeyEvent(QEvent.Type.KeyPress, k, mods, scan, 0, 0, text)

        def settle():
            for _ in range(40):
                QApplication.processEvents()
                if con._anim is None or con._anim.state() != con._anim.State.Running:
                    break
                time.sleep(0.01)
            QApplication.processEvents()

        prefs.data["dev_mode"] = False
        assert not keys.handle(key()) and not con.is_open()         # mod kapalı: " oynatıcıya gider
        assert not keys.handle(key(scan=40))                         # başka fiziksel tuş
        assert keys.handle(key(shift=True, k=_Qt.Key.Key_Eacute, text="é"))   # Shift+": mod açık + konsol
        settle()
        assert prefs.get("dev_mode") and con.is_open() and con.height() > 100, con.height()
        assert con.geometry().top() >= w.titlebar.geometry().bottom()        # başlık çubuğunun altında
        con.edit.setText("open ")
        con.edit.setFocus()
        QApplication.processEvents()
        if QApplication.focusWidget() is con.edit:
            assert not keys.handle(key())                            # komutun içinde " yazılır
            con.edit.clear()
            assert keys.handle(key())                                # boş satırda " kapatır
        else:
            con.close_panel()
        settle()
        assert not con.is_open() and not con.isVisible()
        assert keys.handle(key(scan=0))                              # yapay olay: tuş koduna bakılır
        settle()
        assert con.is_open()
        # komutlar: oynatıcı durumu, duraklat / oynat, sarma, liste, ses, hız, hata kırmızı
        code, out = con.execute("status")
        assert code == 0 and w.current.name in out, out
        assert con.execute("pause")[0] == 0
        assert not w.engine.is_playing()
        code, out = con.execute("seek 0:02")
        assert code == 0 and out.startswith("0:02"), out
        assert abs(w.engine.get_time() - 2000) < 1200, w.engine.get_time()
        assert cli.parse_time("+10", 5000) == 15000 and cli.parse_time("-9", 5000) == 0
        assert cli.parse_time("1:02:03") == 3723000
        code, out = con.execute("list")
        assert code == 0 and "▶" in out, out
        assert con.execute("vol 40") == (0, "40%") and w.engine.volume() == 40
        assert con.execute("speed 1.5") == (0, "1.5x")
        con.execute("speed 1")
        assert con.execute("yokboyle")[0] == 2
        assert con.execute("jump 999")[0] == 1
        assert con.execute("open \"kapanmamış")[0] == 1
        assert con.execute("pref volume") == (0, "40")
        assert con.execute("play")[0] == 0
        assert cli.run(None, ["status"])[0] == 1 and cli.run(None, ["version"])[0] == 0
        reply = cli.handle_request(w, '["status"]')                 # tek örnek sunucusunun cevabı
        assert b'"code": 0' in reply and reply.endswith(b"\n"), reply
        # python -m kamug.cli yolu: gerçek yerel soket, app.serve (ayrı sunucu adı: kurulu kamug'a gitmesin)
        import threading
        from PyQt6.QtNetwork import QLocalServer
        from kamug import app as kapp
        name = f"kamug-smoke-cli-{os.getpid()}"
        QLocalServer.removeServer(name)
        srv = QLocalServer()
        assert srv.listen(name)
        kapp.serve(srv, w)
        box = {}
        th = threading.Thread(target=lambda: box.update(r=cli.send(["vol"], name=name)))
        th.start()
        t0 = time.time()
        while th.is_alive() and time.time() - t0 < 6:
            QApplication.processEvents()
            time.sleep(0.005)
        srv.close()
        assert box.get("r") == (0, "40%"), box
        if "--shots" in sys.argv:
            shots = sys.argv[sys.argv.index("--shots") + 1]
            os.makedirs(shots, exist_ok=True)
            con.execute("help")
            QApplication.processEvents()
            w.grab().save(os.path.join(shots, "console.png"))
        con.execute("clear")
        assert con.output_text() == ""
        # tamamlama + geçmiş
        con.edit.setText("sta")
        con._complete()
        assert con.edit.text() == "status "
        con.edit.setText("theme gra")
        con._complete()
        assert con.edit.text() == "theme graphite "
        con.edit.setText("status")
        con._submit()
        assert prefs.get("console_history")[-1] == "status"
        con.edit.setText("")
        con.eventFilter(con.edit, QKeyEvent(QEvent.Type.KeyPress, _Qt.Key.Key_Up, _Qt.KeyboardModifier.NoModifier))
        assert con.edit.text() == "status"
        con.execute("exit")
        settle()
        assert not con.is_open()
        # yazı alanındayken " normal yazılır (konsol kapalı, mod açık)
        le = QLineEdit(w.main_col)
        le.show()
        le.setFocus()
        QApplication.processEvents()
        if QApplication.focusWidget() is le:
            assert not keys.handle(key())
        le.deleteLater()
        assert keys.handle(key(shift=True))                          # Shift+" modu kapatır
        settle()
        assert not prefs.get("dev_mode") and not con.is_open()

    @step(10, "arka planda hazır bekleme: kapatınca gizlenir, uyanınca dosya açılır, tepsi simgesi")
    def _():
        from kamug import background
        from PyQt6.QtWidgets import QSystemTrayIcon
        assert not background.enabled()                               # varsayılan kapalı
        assert background.autostart_command().endswith(background.ARG)
        prefs.data["background_ready"] = True
        try:
            w.tray.update()
            if QSystemTrayIcon.isSystemTrayAvailable():
                assert w.tray.icon is not None
            w.close()                                                 # kapanmaz, gizlenir
            QApplication.processEvents()
            assert w._hibernating and not w.isVisible() and w.current is None
            assert not w.ui_timer.isActive()
            w.wake()
            w.open_paths([M("image.png")])
            QApplication.processEvents()
            assert w.isVisible() and not w._hibernating and w.ui_timer.isActive()
            assert w.current is not None and os.path.normcase(w.current.path) == os.path.normcase(M("image.png"))
        finally:
            prefs.data["background_ready"] = False
            w.tray.update()
        assert w.tray.icon is None

    GL_STEPS ={"3D model çiziliyor (OpenGL)", "3D: ölçü kutusu ve saydam PNG", "3D: 1-9 kısayolları ve kesit"}

    def run(i=0):
        if i >= len(steps):
            w.close()
            done()
            return
        d, name, fn = steps[i]
        if hidden and name in GL_STEPS:   # ekran dışındaki pencerede OpenGL hiç çizmiyor
            results.append((True, "arayüz: " + name + " — atlandı (ekran dışı; --show ile denetlenir)", 0, ""))
            QTimer.singleShot(0, lambda: run(i + 1))
            return

        def go():
            t0 = time.perf_counter()
            try:
                fn()
                results.append((True, "arayüz: " + name, int((time.perf_counter() - t0) * 1000), ""))
            except Exception:
                results.append((False, "arayüz: " + name, 0, traceback.format_exc(limit=3)))
            run(i + 1)
        QTimer.singleShot(d, go)
    QTimer.singleShot(500, run)


def finish():
    ok = sum(1 for r in results if r[0])
    for passed, name, ms, err in results:
        print(("  OK  " if passed else " FAIL ") + f"{name}" + (f"  ({ms} ms)" if passed else ""))
        if err:
            print("       " + err.strip().replace("\n", "\n       "))
    print(f"\n{ok}/{len(results)} başarılı")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--no-gui" in sys.argv:
        finish()
    QTimer.singleShot(60000, lambda: (results.append((False, "zaman aşımı", 0, "")), finish()))
    gui_tests(finish)
    app.exec()
