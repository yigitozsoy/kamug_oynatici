"""Komut kapısı: oynatıcıyı yazıyla yönetmek için (geliştirici konsolu + komut satırı aynı fonksiyonu kullanır).

    run(win, argv) -> (kod, metin)     win = açık MainWindow (konsol bunu çağırır)

Komut satırından:  python -m kamug.cli status | pause | seek 1:30 | open "D:\\video.mp4" | help
Çalışan kamug varsa istek tek örnek sunucusuna gider (app.py, "\\x02cli" iletisi), cevabı geri yazılır. kamug kapalıysa
yalnızca help / version çalışır; open kamug'u o dosyayla başlatır.
"""
import json
import os
import sys

from .config import prefs
from .i18n import t

# komut → kısa açıklama anahtarı (help sırası da bu)
COMMANDS = {
    "status": "cli_h_status", "open": "cli_h_open", "play": "cli_h_play", "pause": "cli_h_pause",
    "toggle": "cli_h_toggle", "seek": "cli_h_seek", "next": "cli_h_next", "prev": "cli_h_prev",
    "list": "cli_h_list", "jump": "cli_h_jump", "vol": "cli_h_vol", "mute": "cli_h_mute", "speed": "cli_h_speed",
    "full": "cli_h_full", "theater": "cli_h_theater", "sidebar": "cli_h_sidebar", "home": "cli_h_home",
    "snap": "cli_h_snap", "theme": "cli_h_theme", "recent": "cli_h_recent", "pref": "cli_h_pref",
    "version": "cli_h_version", "help": "cli_h_help",
}
OFFLINE = ("help", "version")


def parse_time(s, cur_ms=0):
    """"90", "1:30", "1:02:03", "+10", "-5", "%50" (uzunluğa göre değil; çağıran bilir) → ms. Göreli ise cur'a eklenir."""
    s = s.strip().replace(",", ".")
    rel = s[:1] in "+-"
    sign = -1 if s.startswith("-") else 1
    body = s[1:] if rel else s
    parts = body.split(":")
    if not parts or len(parts) > 3:
        raise ValueError(s)
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    ms = int(sec * 1000)
    return max(0, cur_ms + sign * ms) if rel else ms


def _fmt(ms):
    from .library import fmt_time
    return fmt_time(max(0, int(ms)))


def _kind(item):
    return {"video": t("video"), "audio": t("audio"), "image": t("image"), "model": t("model")}.get(item.kind, item.kind)


def _need_media(win):
    if win.current is None:
        raise _Fail(t("cli_no_media"))


def _need_playable(win):
    _need_media(win)
    if not win.current.is_playable or not win._ensure_engine():
        raise _Fail(t("cli_not_playable"))


class _Fail(Exception):
    pass


def help_text():
    rows = []
    for k, v in COMMANDS.items():
        text = t(v)
        use, _, desc = text.partition("  ") if "  " in text and text.startswith(k + " ") else (k, "", text)
        rows.append((use, desc))
    w = max(len(u) for u, _ in rows)
    return "\n".join(f"{u.ljust(w)}  {d}" for u, d in rows)


def _status(win):
    if win.current is None:
        return t("cli_st_home")
    it = win.current
    lines = [f"{it.name}  ({_kind(it)})", f"{t('cli_st_folder')}: {os.path.dirname(it.path)}"]
    seq = win.lib.items
    if it in seq:
        lines.append(f"{t('cli_st_index')}: {seq.index(it) + 1}/{len(seq)}")
    e = win.engine
    if it.is_playable and e is not None:
        state = t("cli_st_ended") if win._ended else (t("cli_st_playing") if e.is_playing() else t("cli_st_paused"))
        lines.append(f"{t('cli_st_state')}: {state}  {_fmt(e.get_time())} / {_fmt(e.get_length())}")
        lines.append(f"{t('cli_st_volume')}: {e.volume()}%{' (' + t('muted') + ')' if e.muted() else ''}  "
                     f"{t('speed')}: {e.rate():g}x")
    return "\n".join(lines)


def _list(win, args):
    q = " ".join(args).lower()
    seq = win.lib.items
    if not seq:
        return t("cli_list_empty")
    rows = []
    for n, it in enumerate(seq, 1):
        if q and q not in it.name.lower():
            continue
        mark = "▶" if it is win.current else " "
        rows.append(f"{mark} {n:>3}  {it.name}")
    return "\n".join(rows) if rows else t("cli_list_none", q=q)


def _jump(win, args):
    if not args:
        raise _Fail(t("cli_usage", u="jump <n | ad>"))
    seq = win.lib.items
    q = " ".join(args)
    if q.isdigit():
        n = int(q)
        if not 1 <= n <= len(seq):
            raise _Fail(t("cli_out_of_range", n=n, m=len(seq)))
        item = seq[n - 1]
    else:
        hits = [it for it in seq if q.lower() in it.name.lower()]
        if not hits:
            raise _Fail(t("cli_list_none", q=q))
        item = hits[0]
    win.play_item(item)
    return item.name


def _pref(args):
    if not args:
        keys = sorted(prefs.data)
        return "\n".join(f"{k} = {json.dumps(prefs.data[k], ensure_ascii=False)}" for k in keys
                         if k not in ("recent", "console_history", "window_geometry"))
    key = args[0]
    if len(args) == 1:
        if key not in prefs.data:
            raise _Fail(t("cli_no_pref", k=key))
        return json.dumps(prefs.get(key), ensure_ascii=False)
    raw = " ".join(args[1:])
    try:
        val = json.loads(raw)
    except ValueError:
        val = raw
    prefs.set(key, val)
    return f"{key} = {json.dumps(val, ensure_ascii=False)}"


def run(win, argv):
    """Bir komutu çalıştırır → (kod, metin). Kod 0 = tamam, 1 = hata, 2 = bilinmeyen komut."""
    if not argv:
        return 0, help_text()
    cmd, args = argv[0].lower(), argv[1:]
    try:
        if cmd in ("help", "-h", "--help"):
            return 0, help_text()
        if cmd == "version":
            from . import __version__
            return 0, f"kamug {__version__}"
        if cmd not in COMMANDS:
            return 2, t("cli_unknown", c=cmd)
        if win is None:
            return 1, t("cli_not_running")
        return 0, _run_ui(win, cmd, args)
    except _Fail as e:
        return 1, str(e)
    except ValueError as e:
        return 1, t("cli_bad_value", v=str(e))


def _run_ui(win, cmd, args):
    e = win.engine
    if cmd == "status":
        return _status(win)
    if cmd == "open":
        paths = [a for a in args if not a.startswith("--at=")]
        at = next((a[5:] for a in args if a.startswith("--at=")), None)
        if not paths:
            raise _Fail(t("cli_usage", u="open <dosya | klasör> [--at=sn]"))
        p = os.path.abspath(os.path.expanduser(paths[0]))
        if not os.path.exists(p):
            raise _Fail(t("cli_no_file", p=p))
        win.open_paths([p], parse_time(at) if at else None)
        return win.current.name if win.current else p
    if cmd in ("play", "pause", "toggle"):
        _need_media(win)
        if win.current.is_image:
            if cmd == "toggle" or (cmd == "play") != win._slideshow:
                win.toggle_slideshow()
            return t("slideshow") + ": " + (t("on") if win._slideshow else t("off"))
        _need_playable(win)
        e = win.engine
        playing = e.is_playing()
        if cmd == "toggle" or (cmd == "play" and not playing) or (cmd == "pause" and playing):
            win.toggle_play()
            playing = not playing
        return t("cli_st_playing") if playing else t("cli_st_paused")
    if cmd == "seek":
        _need_playable(win)
        if not args:
            raise _Fail(t("cli_usage", u="seek <sn | dk:sn | +10 | -5>"))
        ms = parse_time(args[0], win._display_time())
        win.seek_to(ms)
        return _fmt(ms) + " / " + _fmt(win.engine.get_length())
    if cmd in ("next", "prev"):
        _need_media(win)
        win.play_next() if cmd == "next" else win.play_prev()
        return win.current.name if win.current else ""
    if cmd == "list":
        return _list(win, args)
    if cmd == "jump":
        return _jump(win, args)
    if cmd == "vol":
        if not win._ensure_engine():
            raise _Fail(t("cli_not_playable"))
        if args:
            a = args[0].rstrip("%")
            v = win.engine.volume() + int(a) if a[:1] in "+-" else int(a)
            win.set_volume(v, osd=True)
        return f"{win.engine.volume()}%"
    if cmd == "mute":
        if not win._ensure_engine():
            raise _Fail(t("cli_not_playable"))
        win.toggle_mute()
        return t("muted") if win.engine.muted() else t("volume_pct", v=win.engine.volume())
    if cmd == "speed":
        _need_playable(win)
        if args:
            r = max(0.25, min(4.0, float(args[0].rstrip("x").replace(",", "."))))
            win.engine.set_rate(r)
            win.osd(t("speed") + f": {r:g}x")
        return f"{win.engine.rate():g}x"
    if cmd == "full":
        win.toggle_fullscreen()
        return t("cli_done")
    if cmd == "theater":
        win.toggle_theater()
        return t("on") if win._theater else t("off")
    if cmd == "sidebar":
        win.toggle_sidebar()
        return t("on") if win._sidebar_visible else t("off")
    if cmd == "home":
        win.go_home()
        return t("cli_st_home")
    if cmd == "snap":
        _need_playable(win)
        if not win.current.is_video:
            raise _Fail(t("cli_not_video"))
        win.take_snapshot()
        return getattr(win, "_last_snapshot", "") or t("snapshot_failed")
    if cmd == "theme":
        from .theme import theme, VARIANTS, current_variant
        if args:
            if args[0] not in VARIANTS and args[0] not in ("dark", "light"):
                raise _Fail(t("cli_themes") + " " + ", ".join(VARIANTS))
            theme.apply(args[0])
        else:
            win.toggle_theme()
        return current_variant()
    if cmd == "recent":
        rec = prefs.get("recent", [])
        return "\n".join(f"{n:>2}  {p}" for n, p in enumerate(rec, 1)) or t("cli_list_empty")
    if cmd == "pref":
        return _pref(args)
    return ""


# ------------------------------------------------------------------ komut satırı (python -m kamug.cli)
CLI_TAG = "\x02cli\n"


def send(argv, timeout_ms=5000, name=None):
    """Çalışan kamug'a komut gönderir → (kod, metin) ya da kamug kapalıysa None. name: sunucu adı (test)."""
    from PyQt6.QtNetwork import QLocalSocket
    from .app import SERVER_NAME
    sock = QLocalSocket()
    sock.connectToServer(name or SERVER_NAME)
    if not sock.waitForConnected(300):
        return None
    sock.write((CLI_TAG + json.dumps(argv, ensure_ascii=False)).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    buf = b""
    while sock.waitForReadyRead(timeout_ms):
        buf += bytes(sock.readAll())
        if buf.endswith(b"\n"):
            break
    sock.disconnectFromServer()
    try:
        r = json.loads(buf.decode("utf-8"))
        return int(r["code"]), r["out"]
    except (ValueError, KeyError, TypeError):
        return 1, t("cli_no_reply")


def handle_request(win, payload):
    """app.py sunucusu: "\\x02cli\\n<json argv>" → cevap baytları."""
    try:
        argv = json.loads(payload)
        code, out = run(win, [str(a) for a in argv])
    except Exception as e:  # noqa: BLE001  (istemciye hata dönsün, uygulama düşmesin)
        code, out = 1, f"{type(e).__name__}: {e}"
    return (json.dumps({"code": code, "out": out}, ensure_ascii=False) + "\n").encode("utf-8")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from PyQt6.QtCore import QCoreApplication
    main.app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])   # QLocalSocket için
    res = send(argv) if argv and argv[0].lower() not in OFFLINE else None
    if res is None:
        if argv and argv[0].lower() == "open" and len(argv) > 1:
            import subprocess
            args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "kamug"]
            subprocess.Popen(args + argv[1:], close_fds=True)
            print(t("cli_started"))
            return 0
        res = run(None, argv)
    code, out = res
    if out:
        print(out, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
