"""Arka planda hazır bekleme (tercih: background_ready, varsayılan kapalı).

Açıkken kamug Windows açılışında görünmeden başlar (`kamug.exe --background`), pencere kapatılınca kapanmaz,
gizlenir. Böylece dosya açmak Python + Qt + pencere kurulumunu beklemez; tek örnek sunucusu dosyayı alır ve
hazır pencere hemen görünür. Tamamen kapatmak sistem tepsisindeki simgeden ("Çık").

Not: Claude/Python install manager gibi MSIX paketli bir süreçten çalışırken winreg yazdıkları sanal kayıt
defterine gider; kurulu kamug.exe paketli değildir, gerçek HKCU\\...\\Run'a yazar."""
import os
import sys

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import prefs, BASE_DIR
from .i18n import t

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "kamug"
ARG = "--background"


def enabled():
    return bool(prefs.get("background_ready", False))


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {ARG}'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.join(BASE_DIR, "main.py")}" {ARG}'


def set_autostart(on):
    """Windows açılışında başlatma kaydını yazar / siler. Döndürür: başarılı mı."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def sync_autostart():
    """Kurulu exe açılışında: kayıt tercihle uyumlu olsun (exe taşındıysa yolu da düzelir)."""
    if getattr(sys, "frozen", False):
        set_autostart(enabled())


class Tray(QObject):
    """Arka plan modu açıkken sistem tepsisindeki simge: tıklayınca kamug, menüde Aç / Çık."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.icon = None

    def update(self):
        want = enabled() and QSystemTrayIcon.isSystemTrayAvailable()
        if want and self.icon is None:
            self.icon = QSystemTrayIcon(QApplication.instance().windowIcon(), self)
            self.icon.setToolTip("kamug")
            menu = QMenu()
            menu.addAction(t("bg_open"), self.win.wake)
            menu.addSeparator()
            menu.addAction(t("bg_quit"), self.win.quit_app)
            self._menu = menu                    # QSystemTrayIcon menünün sahibi olmaz
            self.icon.setContextMenu(menu)
            self.icon.activated.connect(self._activated)
            self.icon.show()
        elif not want and self.icon is not None:
            self.icon.hide()
            self.icon.deleteLater()
            self.icon = None

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.win.wake()
