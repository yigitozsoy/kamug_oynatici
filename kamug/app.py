"""Uygulama girişi: tek pencere modu, tema, ana pencere."""
import ctypes
import os
import subprocess
import sys

from . import startup_log
startup_log.start()             # açılış süresi kaydı (startup.log): Qt yüklenmeden önceki an

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QIcon, QFont  # noqa: E402
from PyQt6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from .config import prefs, asset, BASE_DIR  # noqa: E402

SERVER_NAME = "kamug-single-instance-v1"


def _parse_at(argv):
    """--at=SANİYE (yazıt notundaki zaman bağlantısı) → ms ya da None."""
    for a in argv:
        if a.startswith("--at="):
            try:
                return max(0, int(float(a[5:].replace(",", ".")) * 1000))
            except ValueError:
                return None
    return None


def _send_to_running(paths, start_ms=None) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:
        pass
    lines = [os.path.abspath(p) for p in paths]
    if start_ms is not None and lines:
        lines.insert(0, f"\x01at={start_ms}")
    data = ("\n".join(lines) or "\x00").encode("utf-8")
    sock.write(data)
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _bring_to_front(win):
    win.wake()                  # arka planda gizli bekliyorsa zamanlayıcıları da başlatır


def restart(win=None):
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        main_py = os.path.join(BASE_DIR, "main.py")
        args += [main_py] if os.path.exists(main_py) else ["-m", "kamug"]
    if win is not None and win.current is not None:
        args.append(win.current.path)
    if win is not None:
        win._quitting = True        # arka plan modunda bile gerçekten kapansın
        win.close()
    QApplication.instance().quit()
    subprocess.Popen(args, close_fds=True)


def serve(server, win):
    """Tek örnek sunucusu: başka kamug açılışlarından dosya yolları, kamug.cli'den komutlar gelir."""
    def on_conn():
        s = server.nextPendingConnection()
        if s is None:
            return

        def read():
            raw = bytes(s.readAll()).decode("utf-8", errors="ignore")
            from .cli import CLI_TAG, handle_request
            if raw.startswith(CLI_TAG):        # python -m kamug.cli: komutu çalıştır, cevabı geri yaz
                s.write(handle_request(win, raw[len(CLI_TAG):]))
                s.flush()
                return
            got = [p for p in raw.split("\n") if p and p != "\x00"]
            at = None
            for p in [p for p in got if p.startswith("\x01at=")]:
                got.remove(p)
                try:
                    at = int(p[4:])
                except ValueError:
                    pass
            _bring_to_front(win)
            if got:
                win.open_paths(got, at)
        s.readyRead.connect(read)
        s.disconnected.connect(s.deleteLater)
    server.newConnection.connect(on_conn)


def main():
    # Kaynaktan çalışırken (python.exe) görev çubuğunda Python simgesi çıkmasın diye ayrı kimlik veriyoruz.
    # Kurulu exe'de VERMİYORUZ: açık kimliği olan pencerenin simgesini görev çubuğu o kimliği taşıyan bir
    # kısayoldan arıyor, bulamayınca düz pencere simgesi gösteriyordu. Kimlik verilmezse Windows kamug.exe'nin
    # kendi simgesini kullanır ve Başlat / masaüstü kısayollarıyla aynı düğmede toplar (sabitleme de düzgün).
    if not getattr(sys, "frozen", False):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("tamga.kamug")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
    startup_log.mark("qt")
    app = QApplication(sys.argv)
    startup_log.mark("app")
    app.setApplicationName("kamug")
    app.setOrganizationName("tamga")
    # Ana pencerenin closeEvent'i uygulamayı kendisi kapatır; arka plan modunda ana pencere gizliyken
    # kapanan bir iletişim kutusu uygulamayı bitirmesin.
    app.setQuitOnLastWindowClosed(False)
    from .theme import install_font_fallbacks
    install_font_fallbacks()                # Japonca, Göktürk, Arapça... dosya adları ve etiketler için
    f = QFont("Segoe UI Variable Text")
    f.setPointSizeF(9.5)
    app.setFont(f)
    startup_log.mark("fonts")
    ico = asset("logo.ico") if os.path.exists(asset("logo.ico")) else asset("logo.png")
    app.setWindowIcon(QIcon(ico))

    # Qt'nin hazır pencereleri (renk seçici, dosya iletişim kutusu düğmeleri) için çeviri
    try:
        from PyQt6.QtCore import QTranslator, QLibraryInfo
        if prefs.get("language", "tr") == "tr":
            tr = QTranslator(app)
            if tr.load("qtbase_tr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
                app.installTranslator(tr)
    except Exception:
        pass

    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    start_ms = _parse_at(sys.argv[1:])
    from . import background
    hidden = background.ARG in sys.argv and not paths
    if hidden and not background.enabled():      # tercih kapatılmış ama Windows açılış kaydı kalmış
        background.sync_autostart()
        return 0

    server = None
    if (prefs.get("single_instance", True) or background.enabled()) and "--new-window" not in sys.argv:
        if hidden:
            probe = QLocalSocket()
            probe.connectToServer(SERVER_NAME)
            if probe.waitForConnected(300):          # zaten çalışıyor: öne getirmeden çık
                probe.disconnectFromServer()
                return 0
        elif _send_to_running(paths, start_ms):
            return 0
        QLocalServer.removeServer(SERVER_NAME)
        server = QLocalServer()
        server.listen(SERVER_NAME)

    startup_log.mark("single")
    from .theme import theme
    theme.apply()
    startup_log.mark("theme")
    from . import tamga_sync
    tamga_sync.install(prefs, theme)
    from .window import MainWindow
    startup_log.mark("import")
    win = MainWindow(paths, start_ms, hidden=hidden)
    startup_log.mark("window")
    if hidden:
        win.start_hidden()
    else:
        win.show()
        kind = os.path.splitext(paths[0])[1].lower().lstrip(".") if paths else "home"
        QTimer.singleShot(0, lambda: startup_log.finish(kind or "folder"))   # ilk çizimden sonra
    # Oturum kapanırken / bilgisayar kapanırken gizlenmek yerine gerçekten kapan
    app.commitDataRequest.connect(lambda *_: setattr(win, "_quitting", True))
    background.sync_autostart()

    if server is not None:
        serve(server, win)

    # Kurulu exe: dosya türü kayıtları silinmişse onar (yoksa her fotoğrafta Windows güvenlik uyarısı çıkar)
    if getattr(sys, "frozen", False):
        def _repair():
            try:
                from .shell import repair_file_types
                repair_file_types()
            except Exception:
                pass
        QTimer.singleShot(3000, _repair)

    return app.exec()
