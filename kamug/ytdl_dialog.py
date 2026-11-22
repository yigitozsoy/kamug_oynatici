"""Linkten indir penceresi: video linki (YouTube ya da başka site) → bilgi (ad, süre, boyut) → seçilen kalitede
indir → kamug'da aç. Oynatma listesinde videolar tek tek seçilir, sırayla ya da aynı anda indirilir."""
import os
import threading

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import ytdl
from .config import prefs
from .i18n import t
from .widgets import ElidedLabel, ThemedDialog

CONTENTS = ["both", "video", "audio"]
PARALLEL = 3            # "aynı anda" seçilince en çok kaç video birlikte iner


def _mb(b):
    if b is None:
        return "—"
    return f"{b / 1073741824:.2f} GB" if b >= 1073741824 else f"{b / 1048576:.1f} MB"


def _dur(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _process(parent):
    p = QProcess(parent)
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONIOENCODING", "utf-8")
    p.setProcessEnvironment(env)
    p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    return p


class _Job(QObject):
    """Tek videonun indirilmesi (bir yt-dlp süreci). Bot korumasında bir kez tarayıcı gibi tekrar dener."""
    changed = pyqtSignal(object)
    done = pyqtSignal(object)

    def __init__(self, parent, make_cmd, row=None, index=0):
        super().__init__(parent)
        self.make_cmd = make_cmd        # impersonate -> komut
        self.row = row
        self.index = index
        self.impersonate = False
        self.frac = 0.0
        self.speed = None
        self.path = None
        self.out = ""
        self.state = "wait"             # wait | run | merge | retry | done | fail | cancel
        self.proc = None

    def start(self):
        self.state = "run" if self.state != "retry" else "retry"
        self.out = ""
        p = _process(self)
        p.readyReadStandardOutput.connect(self._read)
        p.finished.connect(lambda code, _st: self._finished(code))
        p.errorOccurred.connect(self._error)
        self.proc = p
        cmd = self.make_cmd(self.impersonate)
        p.start(cmd[0], cmd[1:])
        self.changed.emit(self)

    def _read(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self.out = (self.out + data)[-20000:]
        for line in data.splitlines():
            r = ytdl.parse_line(line)
            if r is None:
                continue
            if r[0] == "progress" and r[1] is not None:
                self.frac, self.speed = r[1], r[2]
                self.state = "run"
            elif r[0] == "phase":
                self.state = "merge"
            elif r[0] == "file" and (self.path is None or not os.path.exists(self.path)):
                self.path = r[1]
        self.changed.emit(self)

    def _error(self, err):
        if err == QProcess.ProcessError.FailedToStart and self.proc is not None:
            self.proc = None
            self.state = "fail"
            self.out += "\nyt-dlp"
            self.done.emit(self)

    def _finished(self, code):
        if self.proc is None:
            return
        self._read()
        self.proc = None
        if self.path and os.path.exists(self.path):       # altyazı inmese de (--ignore-errors) video indiyse tamam
            self.state, self.frac = "done", 1.0
        elif not self.impersonate and ytdl.blocked(self.out):
            self.impersonate = True                         # site bot korumasıyla reddetti
            self.state = "retry"
            self.start()
            return
        else:
            self.state = "fail"
        self.changed.emit(self)
        self.done.emit(self)

    def cancel(self):
        if self.proc is not None:
            p, self.proc = self.proc, None
            p.kill()
            p.waitForFinished(2000)
        if self.state not in ("done", "fail"):
            self.state = "cancel"


class DownloadDialog(ThemedDialog):
    _install_progress = pyqtSignal(int, int)
    _install_done = pyqtSignal(str)          # "" = başarılı, yoksa hata metni

    COL_CHK, COL_NUM, COL_TITLE, COL_DUR, COL_SIZE, COL_STATE = range(6)

    def __init__(self, win, url=""):
        super().__init__(win, t("yt_title"))
        self.win = win
        self.info_proc = None
        self.info_buf = ""
        self.entries = []               # liste videoları: {index, id, duration, size, url, title, ...}
        self.single = None              # tek video bilgisi
        self.playlist_title = ""
        self.list_mode = False
        self.jobs = []
        self.downloading = False
        self._installing = False
        self._cancel_install = False
        self._after_tool = None
        self._update_checked = False
        self._sizes_pending = False
        self.setMinimumWidth(600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        lay.addWidget(QLabel(t("yt_link")))
        self.ed_url = QLineEdit(url)
        self.ed_url.setPlaceholderText("https://…")
        self.ed_url.textChanged.connect(self._url_changed)
        lay.addWidget(self.ed_url)
        irow = QHBoxLayout()
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        irow.addWidget(self.lbl_info, 1)
        self.chk_list = QCheckBox(t("yt_playlist"))
        self.chk_list.toggled.connect(lambda _on: self._fetch_info())
        irow.addWidget(self.chk_list)
        lay.addLayout(irow)

        row = QHBoxLayout()
        row.addWidget(QLabel(t("yt_quality")))
        self.cmb_q = QComboBox()
        for q in ytdl.QUALITIES:
            self.cmb_q.addItem(t("yt_q_" + q), q)
        qpref = prefs.get("yt_quality", "best")
        self.cmb_q.setCurrentIndex(max(0, self.cmb_q.findData(qpref)))
        row.addWidget(self.cmb_q)
        row.addSpacing(12)
        row.addWidget(QLabel(t("yt_content")))
        self.cmb_content = QComboBox()
        for c in CONTENTS:
            self.cmb_content.addItem(t("yt_content_" + c), c)
        cpref = "audio" if qpref == "audio" else prefs.get("yt_content", "both")
        self.cmb_content.setCurrentIndex(max(0, self.cmb_content.findData(cpref)))
        row.addWidget(self.cmb_content)
        row.addSpacing(12)
        self.chk_subs = QCheckBox(t("yt_subs"))
        self.chk_subs.setChecked(bool(prefs.get("yt_subs", True)))
        row.addWidget(self.chk_subs)
        row.addStretch(1)
        lay.addLayout(row)
        self.cmb_q.currentIndexChanged.connect(self._format_changed)
        self.cmb_content.currentIndexChanged.connect(self._format_changed)

        # ---- oynatma listesi
        self.tb = QTableWidget(0, 6)
        self.tb.setHorizontalHeaderLabels(["", "#", t("yt_col_title"), t("yt_col_duration"), t("yt_col_size"),
                                           t("yt_col_state")])
        self.tb.verticalHeader().hide()
        self.tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tb.setWordWrap(False)
        h = self.tb.horizontalHeader()
        for c in range(6):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c == self.COL_TITLE
                                   else QHeaderView.ResizeMode.ResizeToContents)
        self.tb.itemChanged.connect(self._item_changed)
        self.tb.cellClicked.connect(self._cell_clicked)
        self.tb.setMinimumHeight(220)
        lay.addWidget(self.tb, 1)
        lrow = QHBoxLayout()
        self.btn_all = QPushButton(t("yt_select_all"))
        self.btn_all.setObjectName("Pill")
        self.btn_all.clicked.connect(lambda: self._check_all(True))
        self.btn_none = QPushButton(t("yt_select_none"))
        self.btn_none.setObjectName("Pill")
        self.btn_none.clicked.connect(lambda: self._check_all(False))
        lrow.addWidget(self.btn_all)
        lrow.addWidget(self.btn_none)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setObjectName("Secondary")
        lrow.addWidget(self.lbl_sum, 1)
        self.lbl_mode = QLabel(t("yt_mode"))
        lrow.addWidget(self.lbl_mode)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem(t("yt_mode_seq"), 1)
        self.cmb_mode.addItem(t("yt_mode_par", n=PARALLEL), PARALLEL)
        self.cmb_mode.setCurrentIndex(1 if int(prefs.get("yt_parallel", 1) or 1) > 1 else 0)
        lrow.addWidget(self.cmb_mode)
        lay.addLayout(lrow)
        self._list_widgets = (self.tb, self.btn_all, self.btn_none, self.lbl_sum, self.lbl_mode, self.cmb_mode)

        crow = QHBoxLayout()
        crow.addWidget(QLabel(t("yt_login")))
        self.cmb_c = QComboBox()
        self.cmb_c.addItem(t("yt_login_none"), "")
        for b in ytdl.BROWSERS:
            self.cmb_c.addItem(b.capitalize(), b)
        self.cmb_c.addItem(t("yt_login_file"), "file")
        cur = prefs.get("yt_cookies", "") or ""
        if cur.lower().endswith(".txt"):
            self.cmb_c.insertItem(self.cmb_c.count() - 1, os.path.basename(cur), cur)
        self.cmb_c.setCurrentIndex(max(0, self.cmb_c.findData(cur)))
        self._cookie_idx = self.cmb_c.currentIndex()
        self.cmb_c.currentIndexChanged.connect(self._cookie_changed)
        crow.addWidget(self.cmb_c)
        crow.addStretch(1)
        lay.addLayout(crow)
        self.lbl_login = QLabel(t("yt_login_desc"))
        self.lbl_login.setObjectName("Secondary")
        self.lbl_login.setWordWrap(True)
        self.lbl_login.setStyleSheet("font-size: 12px;")
        lay.addWidget(self.lbl_login)

        frow = QHBoxLayout()
        frow.addWidget(QLabel(t("yt_folder")))
        self.lbl_folder = ElidedLabel(ytdl.default_folder())
        self.lbl_folder.setObjectName("Secondary")
        frow.addWidget(self.lbl_folder, 1)
        self.btn_folder = QPushButton(t("change"))
        self.btn_folder.setObjectName("Pill")
        self.btn_folder.clicked.connect(self._pick_folder)
        frow.addWidget(self.btn_folder)
        lay.addLayout(frow)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Secondary")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        note = QLabel(t("yt_note"))
        note.setObjectName("Secondary")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px;")
        lay.addWidget(note)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton(t("cancel"))
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_go = QPushButton(t("yt_download"))
        self.btn_go.setObjectName("Primary")
        self.btn_go.clicked.connect(self._start)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_go)
        lay.addLayout(btns)

        self._install_progress.connect(self._on_install_progress)
        self._install_done.connect(self._on_install_done)
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.setInterval(600)
        self._info_timer.timeout.connect(self._fetch_info)
        self._show_list(False)
        self._sync_controls()
        self.chk_list.setChecked(ytdl.playlist_only(url))
        if not ytdl.installed():
            self._status(t("yt_first_time"))
        self._url_changed()

    # ------------------------------------------------------------------ yardımcılar
    def _url(self):
        return ytdl.find_url(self.ed_url.text())

    def _content(self):
        return self.cmb_content.currentData()

    def _status(self, text):
        self.lbl_status.setText(text)

    def _show_list(self, on):
        self.list_mode = on
        for w in self._list_widgets:
            w.setVisible(on)
        self.resize(max(self.width(), 780 if on else 600), 720 if on else self.sizeHint().height())

    def _sync_controls(self):
        busy = self.downloading or self._installing
        url = self._url()
        for w in (self.ed_url, self.cmb_q, self.cmb_content, self.chk_subs, self.chk_list, self.cmb_c,
                  self.btn_folder, self.btn_all, self.btn_none, self.cmb_mode):
            w.setEnabled(not busy)
        self.cmb_q.setEnabled(not busy and self._content() != "audio")
        self.chk_subs.setEnabled(not busy and self._content() != "audio")
        self.chk_list.setVisible(ytdl.is_playlist(url))
        ok = url is not None and not busy
        if self.list_mode:
            ok = ok and (not self.entries or bool(self._selected()))
        self.btn_go.setEnabled(ok)
        self.bar.setVisible(busy)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, t("yt_folder"), ytdl.default_folder())
        if d:
            prefs.set("yt_folder", d)
            self.lbl_folder.setText(d)

    def _cookie_changed(self, i):
        if self.cmb_c.itemData(i) == "file":
            path, _ = QFileDialog.getOpenFileName(self, t("yt_login_file"), os.path.expanduser("~"),
                                                  "cookies.txt (*.txt)")
            self.cmb_c.blockSignals(True)
            if path:
                j = self.cmb_c.findData(path)
                if j < 0:
                    self.cmb_c.insertItem(self.cmb_c.count() - 1, os.path.basename(path), path)
                    j = self.cmb_c.findData(path)
                self.cmb_c.setCurrentIndex(j)
            else:
                self.cmb_c.setCurrentIndex(self._cookie_idx)
            self.cmb_c.blockSignals(False)
        self._cookie_idx = self.cmb_c.currentIndex()
        self._fetch_info()

    def _save_prefs(self):
        prefs.set("yt_quality", self.cmb_q.currentData())
        prefs.set("yt_content", self._content())
        prefs.set("yt_subs", self.chk_subs.isChecked())
        prefs.set("yt_cookies", self.cmb_c.currentData() or "")
        prefs.set("yt_parallel", self.cmb_mode.currentData())

    # ------------------------------------------------------------------ bilgi (indirmeden)
    def _url_changed(self):
        self.chk_list.blockSignals(True)
        if not ytdl.is_playlist(self._url()):
            self.chk_list.setChecked(False)
        self.chk_list.blockSignals(False)
        self._sync_controls()
        self._info_timer.start()

    def _format_changed(self):
        self._sync_controls()
        if self.list_mode and self.entries:
            self._fetch_sizes()
        elif not self.list_mode:
            self._fetch_info()

    def _want_list(self):
        url = self._url()
        return ytdl.is_playlist(url) and (ytdl.playlist_only(url) or self.chk_list.isChecked())

    def _stop_info(self):
        if self.info_proc is not None:
            p, self.info_proc = self.info_proc, None
            p.kill()
            p.waitForFinished(1000)

    def _run_info(self, cmd, on_entry, on_end=None):
        self._stop_info()
        self.info_buf = ""
        p = _process(self)

        def read():
            if self.info_proc is not p:
                return
            self.info_buf += bytes(p.readAllStandardOutput()).decode("utf-8", "replace")
            *lines, self.info_buf = self.info_buf.split("\n")
            for line in lines:
                e = ytdl.parse_entry(line)
                if e:
                    on_entry(e)

        def fin(*_a):
            if self.info_proc is not p:
                return
            read()
            if self.info_buf:
                e = ytdl.parse_entry(self.info_buf)
                if e:
                    on_entry(e)
            self.info_proc = None
            if on_end:
                on_end()
        p.readyReadStandardOutput.connect(read)
        p.finished.connect(fin)
        self.info_proc = p
        p.start(cmd[0], cmd[1:])

    def _fetch_info(self):
        url = self._url()
        if self.downloading:
            return
        if not url:
            self.lbl_info.setText("")
            self._show_list(False)
            return
        if not ytdl.installed():
            return                       # araç indirilince (İndir'e basınca) bilgi gelir
        if ytdl.needs_update_check() and not self._update_checked:
            self._update_checked = True
            p = _process(self)
            p.finished.connect(lambda *_a: (ytdl.mark_checked(), self._fetch_info()))
            p.errorOccurred.connect(lambda *_a: ytdl.mark_checked())
            self.lbl_info.setText(t("yt_info_loading"))
            cmd = ytdl.update_command()
            p.start(cmd[0], cmd[1:])
            return
        cookies = self.cmb_c.currentData() or ""
        self.lbl_info.setText(t("yt_info_loading"))
        if self._want_list():
            self._show_list(True)
            self.entries = []
            self.tb.setRowCount(0)
            self.playlist_title = ""
            self._run_info(ytdl.info_command(url, flat=True, playlist=True, cookies=cookies),
                           self._add_entry, self._list_loaded)
        else:
            self._show_list(False)
            self.single = None

            def got(e):
                self.single = e
                self._show_single()
            self._run_info(ytdl.info_command(url, playlist=False, quality=self.cmb_q.currentData(),
                                             content=self._content(), cookies=cookies),
                           got, lambda: self.single is None and self.lbl_info.setText(t("yt_info_none")))

    def _show_single(self):
        e = self.single
        parts = [f"<b>{e['title']}</b>"]
        if e.get("duration"):
            parts.append(_dur(e["duration"]))
        if e.get("size"):
            parts.append("~" + _mb(e["size"]))
        self.lbl_info.setText("  ·  ".join(parts))

    def _add_entry(self, e):
        if not self.playlist_title and e.get("playlist"):
            self.playlist_title = e["playlist"]
        e["size"] = None                 # düz listede boyut yok; ikinci geçişte gelir
        e["state"] = ""
        self.entries.append(e)
        r = self.tb.rowCount()
        self.tb.blockSignals(True)
        self.tb.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk.setCheckState(Qt.CheckState.Checked)
        self.tb.setItem(r, self.COL_CHK, chk)
        self.tb.setItem(r, self.COL_NUM, QTableWidgetItem(str(e["index"] or r + 1)))
        ti = QTableWidgetItem(e["title"])
        ti.setToolTip(e["title"])
        self.tb.setItem(r, self.COL_TITLE, ti)
        self.tb.setItem(r, self.COL_DUR, QTableWidgetItem(_dur(e.get("duration"))))
        self.tb.setItem(r, self.COL_SIZE, QTableWidgetItem("…"))
        self.tb.setItem(r, self.COL_STATE, QTableWidgetItem(""))
        self.tb.blockSignals(False)
        self._update_summary()

    def _list_loaded(self):
        if not self.entries:
            self.lbl_info.setText(t("yt_info_none"))
            return
        self._fetch_sizes()

    def _fetch_sizes(self):
        """İkinci geçiş: her videonun seçili kalite / içerikteki boyutu (satır satır gelir)."""
        url = self._url()
        if not url or not self.entries:
            return
        for r, e in enumerate(self.entries):
            e["size"] = None
            self.tb.item(r, self.COL_SIZE).setText("…")
        self._sizes_pending = True
        by_id = {e["id"]: r for r, e in enumerate(self.entries)}

        def got(e2):
            r = by_id.get(e2["id"])
            if r is None and 0 < e2["index"] <= len(self.entries):
                r = e2["index"] - 1
            if r is None:
                return
            self.entries[r]["size"] = e2.get("size")
            if e2.get("duration") and not self.entries[r].get("duration"):
                self.entries[r]["duration"] = e2["duration"]
                self.tb.item(r, self.COL_DUR).setText(_dur(e2["duration"]))
            self.tb.item(r, self.COL_SIZE).setText(_mb(e2.get("size")) if e2.get("size") else "?")
            self._update_summary()

        def end():
            self._sizes_pending = False
            for r, e in enumerate(self.entries):
                if e["size"] is None and self.tb.item(r, self.COL_SIZE).text() == "…":
                    self.tb.item(r, self.COL_SIZE).setText("?")
            self._update_summary()
        self._run_info(ytdl.info_command(url, playlist=True, quality=self.cmb_q.currentData(),
                                         content=self._content(), cookies=self.cmb_c.currentData() or ""),
                       got, end)

    # ------------------------------------------------------------------ liste seçimi
    def _selected(self):
        return [r for r in range(self.tb.rowCount())
                if self.tb.item(r, self.COL_CHK).checkState() == Qt.CheckState.Checked]

    def _check_all(self, on):
        self.tb.blockSignals(True)
        for r in range(self.tb.rowCount()):
            self.tb.item(r, self.COL_CHK).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.tb.blockSignals(False)
        self._update_summary()

    def _item_changed(self, it):
        if it.column() == self.COL_CHK:
            self._update_summary()

    def _cell_clicked(self, r, c):
        if c != self.COL_CHK and not self.downloading:   # satırın herhangi bir yerine tıklamak da işaretler
            it = self.tb.item(r, self.COL_CHK)
            it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)

    def _update_summary(self):
        sel = self._selected()
        total = sum(self.entries[r]["size"] or 0 for r in sel)
        unknown = sum(1 for r in sel if not self.entries[r]["size"])
        txt = t("yt_list_summary", sel=len(sel), n=len(self.entries), size=_mb(total) if total else "—")
        if unknown and self._sizes_pending:
            txt += "  ·  " + t("yt_sizes_pending", n=unknown)
        self.lbl_sum.setText(txt)
        name = self.playlist_title or t("yt_playlist_name")
        self.lbl_info.setText(f"<b>{name}</b>  ·  " + t("yt_n_videos", n=len(self.entries)))
        self._sync_controls()

    # ------------------------------------------------------------------ araç kurulumu
    def _ensure_tool(self, then):
        if ytdl.installed():
            then()
            return
        self._installing = True
        self._after_tool = then
        self._cancel_install = False
        self._sync_controls()
        self.bar.setRange(0, 0)
        self._status(t("yt_installing"))

        def work():
            try:
                ytdl.install(lambda a, b: self._install_progress.emit(a, b), lambda: self._cancel_install)
                self._install_done.emit("")
            except InterruptedError:
                self._install_done.emit("cancel")
            except Exception as e:
                self._install_done.emit(str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def _on_install_progress(self, got, total):
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(got * 1000 / total))
            self._status(t("yt_installing") + f"  {_mb(got)} / {_mb(total)}")

    def _on_install_done(self, err):
        self._installing = False
        self._sync_controls()
        if err == "cancel":
            self._status("")
            return
        if err:
            self._status(t("yt_install_failed") + "\n" + err)
            return
        self._status("")
        self._update_checked = True
        then, self._after_tool = self._after_tool, None
        if then:
            then()

    # ------------------------------------------------------------------ indirme
    def _start(self):
        if not self._url():
            return
        self._save_prefs()
        if not ytdl.installed():
            def after():
                if self._want_list():
                    self._fetch_info()           # önce listeyi göster, kullanıcı seçsin
                    self._status(t("yt_pick_then_download"))
                else:
                    self._fetch_info()
                    self._download()
            self._ensure_tool(after)
            return
        if self.list_mode and not self.entries:
            self._fetch_info()
            return
        self._download()

    def _download(self):
        from .thumbs import FFMPEG
        url = self._url()
        folder = self.lbl_folder.text()
        quality, content = self.cmb_q.currentData(), self._content()
        subs, cookies = self.chk_subs.isChecked(), self.cmb_c.currentData() or ""
        if self.list_mode:
            folder = os.path.join(folder, ytdl.safe_name(self.playlist_title or t("yt_playlist_name")))
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            self._status(str(e))
            return
        self._stop_info()
        self.jobs = []
        if self.list_mode:
            for r in self._selected():
                e = self.entries[r]
                vurl = e["url"] or (f"https://www.youtube.com/watch?v={e['id']}" if e["id"] else url)
                name = f"{e['index'] or r + 1:03d} - %(title).120B [%(id)s]"

                def make(imp, vurl=vurl, name=name):
                    return ytdl.download_command(vurl, folder, quality, FFMPEG, subs=subs, cookies=cookies,
                                                 impersonate=imp, content=content, name=name)
                self.jobs.append(_Job(self, make, row=r, index=e["index"] or r + 1))
            self.parallel = max(1, int(self.cmb_mode.currentData() or 1))
        else:
            def make(imp):
                return ytdl.download_command(url, folder, quality, FFMPEG, subs=subs, cookies=cookies,
                                             impersonate=imp, content=content)
            self.jobs.append(_Job(self, make))
            self.parallel = 1
        if not self.jobs:
            return
        for j in self.jobs:
            j.changed.connect(self._job_changed)
            j.done.connect(self._job_done)
            self._set_row_state(j)
        self.downloading = True
        self._sync_controls()
        self.bar.setRange(0, 0)
        self._status(t("yt_starting"))
        self._pump()

    def _pump(self):
        running = sum(1 for j in self.jobs if j.state in ("run", "merge", "retry"))
        for j in self.jobs:
            if running >= self.parallel:
                break
            if j.state == "wait":
                j.start()
                running += 1
        if running == 0 and all(j.state in ("done", "fail", "cancel") for j in self.jobs):
            self._all_done()

    def _set_row_state(self, j):
        if j.row is None:
            return
        txt = {"wait": t("yt_state_wait"), "merge": t("yt_state_merge"), "retry": t("yt_state_retry"),
               "done": t("yt_state_done"), "fail": t("yt_state_fail"), "cancel": t("yt_state_cancel")}.get(j.state)
        if txt is None:
            txt = f"%{int(j.frac * 100)}" if prefs.get("language", "tr") == "tr" else f"{int(j.frac * 100)}%"
        it = self.tb.item(j.row, self.COL_STATE)
        it.setText(txt)
        if j.state == "fail":
            it.setToolTip((t(ytdl.error_hint(j.out)) + "\n" if ytdl.error_hint(j.out) else "") + ytdl.last_error(j.out))
        if j.state in ("run", "merge"):
            self.tb.scrollToItem(it)

    def _job_changed(self, j):
        self._set_row_state(j)
        n = len(self.jobs)
        frac = sum(x.frac if x.state != "done" else 1.0 for x in self.jobs) / n
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(frac * 1000))
        if n == 1:
            if j.state == "merge":
                self.bar.setRange(0, 0)
                self._status(t("yt_merging"))
            elif j.state == "retry":
                self._status(t("yt_retry_protected"))
            elif j.state == "run":
                txt = t("yt_downloading", p=int(j.frac * 100))
                if j.speed:
                    txt += f"  ·  {_mb(j.speed)}/s"
                self._status(txt)
        else:
            done = sum(1 for x in self.jobs if x.state == "done")
            speed = sum(x.speed or 0 for x in self.jobs if x.state == "run")
            txt = t("yt_list_progress", done=done, n=n, p=int(frac * 100))
            if speed:
                txt += f"  ·  {_mb(speed)}/s"
            self._status(txt)

    def _job_done(self, _j):
        if self.downloading:
            self._pump()

    def _all_done(self):
        self.downloading = False
        self._sync_controls()
        ok = sorted((j for j in self.jobs if j.state == "done" and j.path), key=lambda j: j.index)
        failed = [j for j in self.jobs if j.state == "fail"]
        if ok:
            self.win.open_paths([ok[0].path])
        if ok and not failed:
            self._status(t("yt_done"))
            self.accept()
            return
        if len(self.jobs) == 1 and failed:
            j = failed[0]
            hint = ytdl.error_hint(j.out)
            self._status(t("yt_failed") + "\n" + (t(hint) + "\n" if hint else "") + ytdl.last_error(j.out))
            return
        if failed:
            self._status(t("yt_list_result", ok=len(ok), fail=len(failed)))
        else:
            self._status("")

    def _cancel(self):
        if self.downloading:
            self.downloading = False
            for j in self.jobs:
                j.cancel()
                self._set_row_state(j)
            self._sync_controls()
            self._status(t("yt_cancelled"))
            return
        if self._installing:
            self._cancel_install = True
            return
        self._stop_info()
        self.reject()

    def closeEvent(self, e):
        if self.downloading:
            self._cancel()
        self._cancel_install = True
        self._stop_info()
        super().closeEvent(e)

    def reject(self):
        if self.downloading:
            self._cancel()
        self._stop_info()
        super().reject()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and (self.downloading or self._installing):
            self._cancel()
            return
        super().keyPressEvent(e)
