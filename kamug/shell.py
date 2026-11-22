"""Windows Gezgini sağ tık menüsüne "kamug ile aç" ekleme/kaldırma ve dosya türü kayıtlarının onarımı
(yalnızca geçerli kullanıcı).

Not: ProgID adları (gamma.video vb.) uygulamanın eski adından kalır ve bilerek değiştirilmez: Windows'un
"varsayılan uygulama" seçimi (UserChoice) bu adlara bağlı; ad değişirse kullanıcının seçimi boşa düşer ve
internetten inen dosyalarda güvenlik uyarısı çıkar. Kullanıcı bu adları görmez (Gezgin'in Tür sütununda Windows diliyle "Görsel" / "Image" vb. görünür)."""
import os
import sys
import winreg

from .config import BASE_DIR, asset
from .formats import ALL_MEDIA_EXT

KEY_NAME = "Kamug"
OLD_KEY_NAMES = ("GammaPlayer", "VLCPlus")    # eski sürümlerin menü anahtarları
ROOTS = [r"Software\Classes\SystemFileAssociations\video",
         r"Software\Classes\SystemFileAssociations\audio",
         r"Software\Classes\SystemFileAssociations\image",
         r"Software\Classes\Directory"]


def _command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    main_py = os.path.join(BASE_DIR, "main.py")
    if os.path.exists(main_py):
        return f'"{exe}" "{main_py}" "%1"'
    return f'"{exe}" -m kamug "%1"'


def _all_roots():
    roots = list(ROOTS)
    roots += [rf"Software\Classes\SystemFileAssociations\{e}" for e in sorted(ALL_MEDIA_EXT)]
    return roots


MENU_TITLE = "Open with kamug"


def register(title=MENU_TITLE):
    _delete_menu_keys(OLD_KEY_NAMES)
    cmd = _command()
    ico = sys.executable if getattr(sys, "frozen", False) else asset("logo.ico")
    for root in _all_roots():
        key = rf"{root}\shell\{KEY_NAME}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, title)
            if os.path.exists(ico):
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, ico)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    _notify()


def unregister():
    _delete_menu_keys((KEY_NAME,) + OLD_KEY_NAMES)
    _notify()


def _delete_menu_keys(names):
    for root in _all_roots() + [r"Software\Classes\*"]:
        for name in names:
            key = rf"{root}\shell\{name}"
            for sub in (key + r"\command", key):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except OSError:
                    pass


# Gezgin'in "Tür" sütununda görünen ad: Windows'un diliyle, yanında uygulama adı olmadan (kurulumdaki {cm:Type…} ile aynı)
TYPE_NAMES = {"video": ("Video", "Video"), "audio": ("Ses", "Audio"), "image": ("Görsel", "Image"),
              "model": ("3D model", "3D model")}


def _windows_is_turkish():
    try:
        import ctypes
        return (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x1F
    except Exception:
        return False


def type_names():
    i = 0 if _windows_is_turkish() else 1
    return {k: v[i] for k, v in TYPE_NAMES.items()}
FTA_OPEN_IS_SAFE = 0x00010000


def repair_file_types(exe=None):
    """Kurulumun yazdığı gamma.video / .audio / .image / .model kayıtlarını onarır.

    Dosya türleri kamug'a bağlıyken (Varsayılan uygulamalar) bu anahtarlar silinirse Windows, internetten
    inmiş (MOTW) her dosyada "Güvenlik uyarısı - bu dosyayı açmak istiyor musunuz?" diye sorar. EditFlags =
    FTA_OpenIsSafe bu soruyu kapatır. Yalnızca eksik ya da yanlış olan değerler yazılır. Değişiklik olduysa True."""
    if exe is None:
        if not getattr(sys, "frozen", False):
            return False
        exe = sys.executable
    cmd = f'"{exe}" "%1"'
    changed = False

    def ensure(sub, name, kind, value):
        nonlocal changed
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                cur, typ = winreg.QueryValueEx(k, name)
                if cur == value and typ == kind:
                    return
        except OSError:
            pass
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub) as k:
            winreg.SetValueEx(k, name, 0, kind, value)
        changed = True

    for prog, desc in type_names().items():
        base = rf"Software\Classes\gamma.{prog}"
        ensure(base, "", winreg.REG_SZ, desc)
        ensure(base, "EditFlags", winreg.REG_DWORD, FTA_OPEN_IS_SAFE)
        ensure(base + r"\DefaultIcon", "", winreg.REG_SZ, f"{exe},0")
        ensure(base + r"\shell\open\command", "", winreg.REG_SZ, cmd)
    app = r"Software\Classes\Applications\kamug.exe"
    ensure(app, "FriendlyAppName", winreg.REG_SZ, "kamug")
    ensure(app + r"\shell\open\command", "", winreg.REG_SZ, cmd)
    if changed:
        _notify()
    return changed


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass
