"""Gelişmiş okuma (el yazısı + formüller): küçük bir görsel-dil modeli (Qwen3-VL-4B, Apache 2.0) llama.cpp (MIT) ile
sayfayı Türkçe metin + LaTeX formül olarak yazar. Program ve model kuruluma gömülmez, ilk kullanımda bir kez iner
(~2,9 GB); ekran kartında (Vulkan, her marka) çalışır, sığmayan kısmı işlemciye kalır.

Denemede (el yazısı ders videosu): Türkçe karakterler ve kesirli formüller doğru; 2B model satır atlıyordu.
Model bazen biçimi karıştırır (tablo kalıbı, kod bloğu), aynı satırı tekrarlar ya da sayfada olmayanı "tamamlar":
istem (PROMPT) bunu yasaklar, clean() biçimi düzeltir."""
import os
import re
import subprocess
import time
import zipfile

from .config import DATA_DIR

TOOL_DIR = os.path.join(DATA_DIR, "tools", "llama")
MODEL_DIR = os.path.join(DATA_DIR, "models")
# Denenmiş sürümler sabitlenir
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b12606/llama-b12606-bin-win-vulkan-x64.zip"
_HF = "https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/"
MODEL_FILE, MMPROJ_FILE = "Qwen3VL-4B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
SIZES_MB = {"llama": 37, MODEL_FILE: 2382, MMPROJ_FILE: 433}
TOTAL_MB = sum(SIZES_MB.values())
_KEEP = re.compile(r"(llama-mtmd-cli\.exe|ggml[\w-]*\.dll|llama\.dll|llama-common\.dll|mtmd\.dll|libomp\.dll)$", re.I)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROMPT = ("Görüntüdeki yazıları yukarıdan aşağıya, yazıldığı gibi aktar. Yalnızca görüntüde gerçekten yazılı olanı "
          "yaz: soruları çözme, eksik satırları tamamlama, yorum ekleme. Türkçe karakterleri koru (ç ğ ı İ ö ş ü). "
          "Matematiksel ifadeleri $...$ içinde LaTeX olarak yaz. Düz Markdown kullan; yalnızca görüntüde gerçek bir "
          "tablo varsa Markdown tablosu kullan. Yazı bitince dur.")


def exe_path():
    return os.path.join(TOOL_DIR, "llama-mtmd-cli.exe")


def model_path():
    return os.path.join(MODEL_DIR, MODEL_FILE)


def mmproj_path():
    return os.path.join(MODEL_DIR, MMPROJ_FILE)


def missing_downloads():
    """[(ad, url, hedef, MB, zip mi)]"""
    out = []
    if not os.path.isfile(exe_path()):
        out.append(("llama.cpp", LLAMA_URL, os.path.join(TOOL_DIR, "llama.zip"), SIZES_MB["llama"], True))
    for f in (MMPROJ_FILE, MODEL_FILE):
        if not os.path.isfile(os.path.join(MODEL_DIR, f)):
            out.append((f, _HF + f, os.path.join(MODEL_DIR, f), SIZES_MB[f], False))
    return out


def installed():
    return not missing_downloads()


def _unzip(zpath):
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            base = os.path.basename(n)
            if _KEEP.match(base):
                with z.open(n) as src, open(os.path.join(TOOL_DIR, base), "wb") as dst:
                    dst.write(src.read())
    os.remove(zpath)
    if not os.path.isfile(exe_path()):
        raise OSError("llama-mtmd-cli.exe")


def download_all(progress=None, cancelled=lambda: False):
    """progress(ad, indirilen, toplam)"""
    from .transcript import fetch
    for name, url, dest, _mb, is_zip in missing_downloads():
        fetch(url, dest, (lambda a, b, n=name: progress(n, a, b)) if progress else None, cancelled)
        if is_zip:
            _unzip(dest)


def command(image):
    # -ngl verilmez: llama.cpp ekran kartı belleğine sığdığı kadarını kendisi yerleştirir (99 verince 4 GB kartta çöküyor)
    return [exe_path(), "-m", model_path(), "--mmproj", mmproj_path(), "--image", image, "-p", PROMPT,
            "--temp", "0", "--repeat-penalty", "1.1", "-n", "900", "-c", "8192"]


def read_page(image, cancelled=lambda: False):
    """Tek sayfa → temizlenmiş Markdown (+ $LaTeX$)."""
    p = subprocess.Popen(command(image), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW, cwd=TOOL_DIR)
    chunks = []
    import threading

    def pump():
        for b in iter(lambda: p.stdout.read(4096), b""):
            chunks.append(b)
    th = threading.Thread(target=pump, daemon=True)
    th.start()
    while p.poll() is None:
        if cancelled():
            p.kill()
            raise InterruptedError
        time.sleep(0.2)
    th.join(5)
    return clean(b"".join(chunks).decode("utf-8", "replace"))


def read_files(paths, cancelled=lambda: False, progress=None):
    """screen_text.run için okuyucu: [metin]. progress(i, n)."""
    out = []
    for i, path in enumerate(paths):
        out.append(read_page(path, cancelled))
        if progress:
            progress(i + 1, len(paths))
    return out


# ------------------------------------------------------------------ çıktı temizliği
_MATH_HINT = re.compile(r"\\(frac|sigma|mu|leq|geq|le|ge|sqrt|sum|int|alpha|beta|lambda|pi|cdot|times|infty|left|right)"
                        r"\b|\^|_\{")


def _wrap_math(line):
    """$ içermeyen ama LaTeX komutu olan satırı $...$ içine alır (madde işaretini dışarıda bırakır)."""
    if "$" in line or not _MATH_HINT.search(line) or line.lstrip().startswith("|"):
        return line
    m = re.match(r"^(\s*(?:[-*]|\(?[a-zçğıöşü0-9]{1,2}[).])\s+)(.*)$", line, re.I)
    head, body = (m.group(1), m.group(2)) if m else ("", line)
    return f"{head}${body.strip()}$"


def clean(text):
    """Modelin çıktısını düz Markdown + $LaTeX$ yapar."""
    t = text.replace("\r", "")
    t = re.sub(r"^```[a-z]*\s*$", "", t, flags=re.M)                       # kod bloğu çitleri
    t = re.sub(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}", "", t)          # uydurma resim bağlantıları
    t = re.sub(r"\\(begin|end)\{(tabular|center|array|table)\}(\{[^}]*\})?", "\n", t)
    t = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", t)
    t = re.sub(r"\\(hline|centering)\b", "", t)
    out, seen = [], {}
    for ln in t.split("\n"):
        ln = re.sub(r"\s*\\\\\s*$", "", ln).rstrip()                          # satır sonu \\
        if ln.strip() in ("&", "---"):
            ln = ""
        ln = _wrap_math(ln)
        key = ln.strip()
        if key:
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2 or (out and out[-1].strip() == key):            # tekrar döngüsü
                continue
        out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ------------------------------------------------------------------ ekranda gösterim
_SYM = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ", "lambda": "λ",
        "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω", "Sigma": "Σ",
        "Delta": "Δ", "Omega": "Ω", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
        "approx": "≈", "times": "×", "cdot": "·", "pm": "±", "infty": "∞", "sum": "Σ", "int": "∫",
        "rightarrow": "→", "to": "→", "Rightarrow": "⇒", "in": "∈", "sqrt": "√", "partial": "∂", "ldots": "…",
        "dots": "…", "%": "%"}
_SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _group(s, i):
    """s[i] '{' ise eşleşen kapanışa kadar içerik ve sonraki indis; değilse tek karakter."""
    if i < len(s) and s[i] == "{":
        depth = 0
        for j in range(i, len(s)):
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                return s[i + 1:j], j + 1
        return s[i + 1:], len(s)
    return (s[i], i + 1) if i < len(s) else ("", i)


def _math_text(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:])
            name = m.group(1)
            i += len(m.group(0))
            if name in ("frac", "dfrac", "tfrac"):
                a, i = _group(s, i)
                b, i = _group(s, i)
                a, b = _math_text(a), _math_text(b)
                wrap = (lambda x: x if re.fullmatch(r"[\w.,]+", x) else f"({x})")
                out.append(f"{wrap(a)}/{wrap(b)}")
            elif name == "sqrt":
                a, i = _group(s, i)
                out.append(f"√({_math_text(a)})" if len(a) > 1 else "√" + _math_text(a))
            elif name in ("left", "right", "displaystyle", "mathrm", "text", "mathbf", "operatorname", ",", ";",
                          "!", " ", "quad", "qquad"):
                if name in ("mathrm", "text", "mathbf", "operatorname"):
                    a, i = _group(s, i)
                    out.append(_math_text(a))
                elif name in ("quad", "qquad", ",", ";", " "):
                    out.append(" ")
            else:
                out.append(_SYM.get(name, name))
        elif c in "^_":
            a, i = _group(s, i + 1)
            a = _math_text(a)
            ok = "0123456789+-=()n" if c == "^" else "0123456789+-=()"
            if a and all(ch in ok for ch in a):
                out.append(a.translate(_SUP if c == "^" else _SUB))
            else:
                out.append(c + (a if len(a) == 1 else f"({a})"))
        elif c in "{}":
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def to_display(text):
    """$...$ / $$...$$ içindeki LaTeX'i okunur Unicode'a çevirir (panelde gösterim; kayıtlarda LaTeX kalır)."""
    t = re.sub(r"\$\$(.+?)\$\$", lambda m: _math_text(m.group(1)), text, flags=re.S)
    t = re.sub(r"\$(.+?)\$", lambda m: _math_text(m.group(1)), t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    return t
