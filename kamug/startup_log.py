"""Açılış süresi kaydı: her açılışta aşamaların süresini %LOCALAPPDATA%\\kamug\\startup.log dosyasına yazar.

Soğuk açılış (bilgisayar yeni açılınca) burada yeniden üretilemediği için, yavaşlığın hangi aşamada olduğunu
sonradan görebilmek için tutulur. Son 30 açılış saklanır; maliyeti birkaç milisaniye.
"""
import ctypes
import os
import sys
import time

_marks = []
_t0 = None          # süreç oluşturulma anı (perf_counter cinsinden)
_done = False


def _process_age() -> float:
    """Sürecin kaç saniye önce oluşturulduğu (PyInstaller önyükleyicisi ve Python başlangıcı dahil)."""
    try:
        k32 = ctypes.windll.kernel32
        ft = [ctypes.c_ulonglong() for _ in range(4)]
        if not k32.GetProcessTimes(ctypes.c_void_p(-1), *[ctypes.byref(x) for x in ft]):
            return 0.0
        now = ctypes.c_ulonglong()
        k32.GetSystemTimePreciseAsFileTime(ctypes.byref(now))
        return max(0.0, (now.value - ft[0].value) / 1e7)
    except Exception:
        return 0.0


def start():
    global _t0
    if _t0 is None:
        _t0 = time.perf_counter() - _process_age()
        _marks.append(("python", time.perf_counter() - _t0))


def mark(name: str):
    if _t0 is not None and not _done:
        _marks.append((name, time.perf_counter() - _t0))


def finish(what: str = ""):
    """İlk çizimden sonra çağrılır; satırı dosyaya ekler."""
    global _done
    if _t0 is None or _done:
        return
    mark("shown")
    _done = True
    try:
        from .config import DATA_DIR
        path = os.path.join(DATA_DIR, "startup.log")
        boot = ""
        try:
            boot = f" boot+{ctypes.windll.kernel32.GetTickCount64() / 60000:.0f}dk"
        except Exception:
            pass
        parts = " ".join(f"{n}={t:.2f}" for n, t in _marks)
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')}{boot} "
                f"{'exe' if getattr(sys, 'frozen', False) else 'src'} {what} | {parts}\n")
        try:
            with open(path, encoding="utf-8") as f:
                old = f.readlines()[-29:]
        except OSError:
            old = []
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(old + [line])
    except Exception:
        pass
