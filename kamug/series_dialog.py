"""Dizi / film penceresi: ad önerisi ve toplu yeniden adlandırma, altyazı eşleme ve gömme, intro ayarı."""
import os
import subprocess

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
                             QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QMessageBox,
                             QProgressDialog, QAbstractItemView)

from . import series as ser
from .config import prefs
from .i18n import t
from .library import fmt_time
from .widgets import ThemedDialog


def _parse_time(text):
    """"1:10", "01:10", "70", "1:02:03" -> ms; geçersizse None."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.replace(",", ".").split(":")]
    except ValueError:
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return int(sec * 1000)


def _ep_label(ep):
    s = f"S{ep.season:02d}E{ep.episode:02d}"
    return s + (f"-E{ep.episode2:02d}" if ep.episode2 else "")


class _Worker(QThread):
    """Uzun işler (gömme, intro arama) için: ilerleme bildirir, iptal edilebilir."""
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancelled = False

    def run(self):
        try:
            self.finished_ok.emit(self.fn(self))
        except Exception as e:  # pragma: no cover
            self.failed.emit(str(e))


class SeriesDialog(ThemedDialog):
    def __init__(self, win, item):
        self.win = win
        self.item = item
        self.series = win._series
        self.movie = win._movie
        name = self.series.title if self.series else (self.movie.title if self.movie else item.title)
        super().__init__(win, t("series_title", name=name) if self.series else t("act_movie") + ": " + name)
        self.resize(860, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        if self.series:
            n_seasons = len(self.series.seasons())
            info = QLabel(t("series_count", n=len(self.series.episodes), s=n_seasons))
            info.setObjectName("Secondary")
            lay.addWidget(info)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        if self.series:
            self.tabs.addTab(self._tab_rename(), t("tab_rename"))
            self.tabs.addTab(self._tab_subs(), t("tab_subs"))
            self.tabs.addTab(self._tab_intro(), t("tab_intro"))
        else:
            self.tabs.addTab(self._tab_movie(), t("tab_rename"))
        foot = QHBoxLayout()
        foot.addStretch(1)
        b = QPushButton(t("close"))
        b.clicked.connect(self.accept)
        foot.addWidget(b)
        lay.addLayout(foot)

    # ------------------------------------------------------------------ yardımcılar
    def _refresh_series(self):
        """Dosyalar değişince diziyi klasörden yeniden oku."""
        cur = self.win.current
        if cur is not None and cur.is_video:
            s = ser.series_for(cur.path, self.win._folder_videos(cur))
            if s is not None:
                self.series = s
                self.win._series = s

    def _table(self, headers):
        tb = QTableWidget(0, len(headers))
        tb.setHorizontalHeaderLabels(headers)
        tb.verticalHeader().hide()
        tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tb.setWordWrap(False)
        h = tb.horizontalHeader()
        for i in range(len(headers)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i else QHeaderView.ResizeMode.ResizeToContents)
        return tb

    def _run(self, fn, label, total, on_done):
        dlg = QProgressDialog(label, t("cancel"), 0, max(1, total), self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        w = _Worker(fn)
        self._worker = w
        w.progress.connect(lambda i, n: (dlg.setMaximum(max(1, n)), dlg.setValue(i)))
        dlg.canceled.connect(lambda: setattr(w, "cancelled", True))

        def fin(res):
            dlg.close()
            on_done(res)

        def fail(msg):
            dlg.close()
            QMessageBox.warning(self, self.windowTitle(), msg)
        w.finished_ok.connect(fin)
        w.failed.connect(fail)
        w.start()
        dlg.show()

    # ------------------------------------------------------------------ adlar
    def _tab_rename(self):
        page = QWidget()
        v = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("series_name")))
        self.ed_title = QLineEdit(self.series.title)
        self.ed_title.textChanged.connect(self._fill_rename)
        row.addWidget(self.ed_title, 1)
        row.addSpacing(12)
        row.addWidget(QLabel(t("name_format")))
        self.cmb_fmt = QComboBox()
        for key in ser.NAME_FORMATS:
            self.cmb_fmt.addItem("", key)
        i = self.cmb_fmt.findData(prefs.get("series_name_format", "dash"))
        self.cmb_fmt.setCurrentIndex(max(0, i))
        self.cmb_fmt.currentIndexChanged.connect(self._fmt_changed)
        row.addWidget(self.cmb_fmt)
        v.addLayout(row)
        self.chk_subs_rename = QCheckBox(t("rename_subs_too"))
        self.chk_subs_rename.setChecked(True)
        v.addWidget(self.chk_subs_rename)
        self.tb_rename = self._table(["", t("rename_old"), t("rename_new")])
        v.addWidget(self.tb_rename, 1)
        self.lbl_rename = QLabel("")
        self.lbl_rename.setObjectName("Secondary")
        v.addWidget(self.lbl_rename)
        bar = QHBoxLayout()
        bar.addStretch(1)
        self.btn_rename = QPushButton(t("rename_apply"))
        self.btn_rename.setObjectName("Primary")
        self.btn_rename.clicked.connect(self._apply_rename)
        bar.addWidget(self.btn_rename)
        v.addLayout(bar)
        self._fill_rename()
        return page

    def _fmt_changed(self):
        prefs.set("series_name_format", self.cmb_fmt.currentData())
        self._fill_rename()

    def _fill_rename(self):
        title = self.ed_title.text().strip() or self.series.title
        ep0 = self.series.episodes[0][1]
        for i in range(self.cmb_fmt.count()):
            self.cmb_fmt.setItemText(i, ser.episode_name(title, ep0, self.cmb_fmt.itemData(i)))
        self._plan = ser.rename_plan(self.series, title, self.cmb_fmt.currentData())
        tb = self.tb_rename
        tb.setRowCount(len(self._plan))
        for r, (old, new) in enumerate(self._plan):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            tb.setItem(r, 0, chk)
            tb.setItem(r, 1, QTableWidgetItem(os.path.basename(old)))
            tb.setItem(r, 2, QTableWidgetItem(os.path.basename(new)))
        self.lbl_rename.setText("" if self._plan else t("rename_none"))
        self.btn_rename.setEnabled(bool(self._plan))

    def _apply_rename(self):
        pairs = [self._plan[r] for r in range(self.tb_rename.rowCount())
                 if self.tb_rename.item(r, 0).checkState() == Qt.CheckState.Checked]
        if not pairs:
            return
        if self.chk_subs_rename.isChecked():
            prefer = "tr" if prefs.get("language", "tr") == "tr" else "en"
            subs = ser.match_subtitles(self.series, ser.list_subtitles(self.series.folder), prefer)
            taken = set()
            for old, new in list(pairs):
                sp = subs.get(old)
                if sp and os.path.normcase(os.path.dirname(sp)) == os.path.normcase(os.path.dirname(old)):
                    target = ser.sub_rename_target(new, sp)
                    if os.path.normcase(target) != os.path.normcase(sp) and target.lower() not in taken:
                        taken.add(target.lower())
                        pairs.append((sp, target))
        done, errors = self.win.apply_renames(pairs)
        self._refresh_series()
        self.ed_title.blockSignals(True)
        self.ed_title.setText(self.series.title)
        self.ed_title.blockSignals(False)
        self._fill_rename()
        self._fill_subs()
        self._fill_intro()
        self.win.osd(t("rename_done", n=done))
        if errors:
            QMessageBox.warning(self, t("rename_apply"), t("rename_errors") + "\n\n" + "\n".join(errors[:15]))

    # ------------------------------------------------------------------ film
    def _tab_movie(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(t("rename_old") + ": " + self.item.name))
        row = QHBoxLayout()
        row.addWidget(QLabel(t("movie_rename")))
        ext = os.path.splitext(self.item.path)[1]
        self.ed_movie = QLineEdit(ser.movie_name(self.movie) + ext if self.movie else self.item.name)
        row.addWidget(self.ed_movie, 1)
        v.addLayout(row)
        bar = QHBoxLayout()
        bar.addStretch(1)
        b = QPushButton(t("rename_apply"))
        b.setObjectName("Primary")
        b.clicked.connect(self._apply_movie)
        bar.addWidget(b)
        v.addLayout(bar)
        v.addStretch(1)
        return page

    def _apply_movie(self):
        new = self.ed_movie.text().strip()
        if not new or new == self.item.name:
            return
        target = os.path.join(os.path.dirname(self.item.path), new)
        pairs = [(self.item.path, target)]
        # Aynı adlı altyazılar da (Film.2010.srt, Film.2010.tr.srt)
        stem = os.path.splitext(self.item.path)[0]
        for sp in ser.list_subtitles(os.path.dirname(self.item.path)):
            if os.path.basename(sp).lower().startswith(os.path.basename(stem).lower()):
                pairs.append((sp, ser.sub_rename_target(target, sp)))
        done, errors = self.win.apply_renames(pairs)
        self.win.osd(t("rename_done", n=done))
        if errors:
            QMessageBox.warning(self, t("rename_apply"), t("rename_errors") + "\n\n" + "\n".join(errors))
        else:
            self.accept()

    # ------------------------------------------------------------------ altyazılar
    def _tab_subs(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.lbl_subs = QLabel("")
        self.lbl_subs.setWordWrap(True)
        v.addWidget(self.lbl_subs)
        chk = QCheckBox(t("subs_auto_load"))
        chk.setChecked(bool(prefs.get("series_subs", True)))
        chk.toggled.connect(lambda on: prefs.set("series_subs", on))
        v.addWidget(chk)
        self.tb_subs = self._table([t("col_episode"), t("col_video"), t("col_subtitle")])
        v.addWidget(self.tb_subs, 1)
        desc = QLabel(t("subs_embed_desc"))
        desc.setObjectName("Secondary")
        desc.setWordWrap(True)
        v.addWidget(desc)
        bar = QHBoxLayout()
        self.chk_keep = QCheckBox(t("subs_keep_original"))
        bar.addWidget(self.chk_keep)
        bar.addStretch(1)
        self.btn_embed = QPushButton(t("subs_embed"))
        self.btn_embed.setObjectName("Primary")
        self.btn_embed.clicked.connect(self._embed)
        bar.addWidget(self.btn_embed)
        v.addLayout(bar)
        self._fill_subs()
        return page

    def _fill_subs(self):
        if not hasattr(self, "tb_subs"):
            return
        prefer = "tr" if prefs.get("language", "tr") == "tr" else "en"
        self._subs = ser.match_subtitles(self.series, ser.list_subtitles(self.series.folder), prefer)
        eps = self.series.episodes
        self.tb_subs.setRowCount(len(eps))
        for r, (p, ep) in enumerate(eps):
            self.tb_subs.setItem(r, 0, QTableWidgetItem(_ep_label(ep)))
            self.tb_subs.setItem(r, 1, QTableWidgetItem(os.path.basename(p)))
            sp = self._subs.get(p)
            it = QTableWidgetItem(os.path.basename(sp) if sp else "—")
            if not sp:
                it.setForeground(Qt.GlobalColor.gray)
            self.tb_subs.setItem(r, 2, it)
        n = len(self._subs)
        self.lbl_subs.setText(t("subs_found", n=n, m=len(eps)) if n else t("subs_none"))
        self.btn_embed.setEnabled(n > 0)

    def _embed(self):
        jobs = [(v, s) for v, s in self._subs.items() if os.path.exists(v) and os.path.exists(s)]
        if not jobs:
            return
        if QMessageBox.question(self, t("subs_embed"), t("subs_embed_confirm", n=len(jobs))) \
                != QMessageBox.StandardButton.Yes:
            return
        keep = self.chk_keep.isChecked()
        released = self.win.release_current_file([v for v, _ in jobs])
        from .thumbs import FFMPEG
        out_dir = os.path.join(self.series.folder, t("subs_out_folder")) if keep else None

        def work(worker):
            from PyQt6.QtCore import QFile
            done, errors, renamed = 0, [], {}
            for i, (video, sub) in enumerate(jobs):
                if worker.cancelled:
                    break
                worker.progress.emit(i, len(jobs))
                base = os.path.splitext(os.path.basename(video))[0]
                if keep:
                    os.makedirs(out_dir, exist_ok=True)
                    final = os.path.join(out_dir, base + ".mkv")
                else:
                    final = os.path.splitext(video)[0] + ".mkv"
                tmp = os.path.splitext(final)[0] + ".kamug-tmp.mkv"
                r = subprocess.run(ser.embed_command(FFMPEG, video, sub, tmp), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                    errors.append(f"{os.path.basename(video)}: {(r.stderr or '').strip()[-200:]}")
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    continue
                try:
                    if not keep:
                        if not QFile.moveToTrash(video):
                            raise OSError(t("trash_failed"))
                        if os.path.exists(final):          # mp4'ün yanında aynı adlı mkv varsa o da gitsin
                            QFile.moveToTrash(final)
                    os.replace(tmp, final)
                    renamed[video] = final
                    done += 1
                except OSError as e:
                    errors.append(f"{os.path.basename(video)}: {e}")
            worker.progress.emit(len(jobs), len(jobs))
            return done, errors, renamed

        def finished(res):
            done, errors, renamed = res
            win = self.win
            win.lib.refresh()
            win._refresh_sidebar()
            if released:
                path, pos = released
                from .library import Library
                it = Library.find(renamed.get(path, path), win.lib.all_items)
                if it:
                    win.load_item(it, start_ms=pos)
            self._refresh_series()
            self._fill_rename()
            self._fill_subs()
            win.osd(t("subs_embed_done", n=done))
            if errors:
                QMessageBox.warning(self, t("subs_embed"), "\n".join(errors[:12]))
        self._run(work, t("subs_embedding"), len(jobs), finished)

    # ------------------------------------------------------------------ intro
    def _tab_intro(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel("<b>" + t("intro_manual") + "</b>"))
        d = QLabel(t("intro_manual_desc"))
        d.setObjectName("Secondary")
        d.setWordWrap(True)
        v.addWidget(d)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("intro_start")))
        self.ed_a = QLineEdit()
        self.ed_a.setPlaceholderText("0:00")
        self.ed_a.setFixedWidth(90)
        row.addWidget(self.ed_a)
        row.addSpacing(10)
        row.addWidget(QLabel(t("intro_end")))
        self.ed_b = QLineEdit()
        self.ed_b.setPlaceholderText("1:30")
        self.ed_b.setFixedWidth(90)
        row.addWidget(self.ed_b)
        b = QPushButton(t("save"))
        b.clicked.connect(self._save_manual)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.chk_autoskip = QCheckBox(t("intro_auto_skip"))
        self.chk_autoskip.toggled.connect(lambda on: ser.store.update(self.series.key, auto_skip=True if on else None))
        v.addWidget(self.chk_autoskip)
        v.addSpacing(8)
        v.addWidget(QLabel("<b>" + t("intro_detect") + "</b>"))
        d2 = QLabel(t("intro_detect_desc"))
        d2.setObjectName("Secondary")
        d2.setWordWrap(True)
        v.addWidget(d2)
        self.tb_intro = self._table([t("col_episode"), t("col_video"), t("tab_intro")])
        v.addWidget(self.tb_intro, 1)
        bar = QHBoxLayout()
        reset = QPushButton(t("intro_reset"))
        reset.clicked.connect(self._reset_intro)
        bar.addWidget(reset)
        bar.addStretch(1)
        bdet = QPushButton(t("intro_detect"))
        bdet.setObjectName("Primary")
        bdet.clicked.connect(self._detect_all)
        bar.addWidget(bdet)
        v.addLayout(bar)
        self._fill_intro()
        return page

    def _fill_intro(self):
        if not hasattr(self, "tb_intro"):
            return
        d = ser.store.get(self.series.key)
        man = d.get("intro")
        self.ed_a.setText(fmt_time(man[0]) if man else "")
        self.ed_b.setText(fmt_time(man[1]) if man else "")
        self.chk_autoskip.blockSignals(True)
        self.chk_autoskip.setChecked(bool(d.get("auto_skip")))
        self.chk_autoskip.blockSignals(False)
        eps = self.series.episodes
        self.tb_intro.setRowCount(len(eps))
        for r, (p, ep) in enumerate(eps):
            self.tb_intro.setItem(r, 0, QTableWidgetItem(_ep_label(ep)))
            self.tb_intro.setItem(r, 1, QTableWidgetItem(os.path.basename(p)))
            rng = ser.store.intro_for(self.series, p)
            known = ser.store.auto_known(self.series, p)
            txt = (t("intro_range", a=fmt_time(rng[0]), b=fmt_time(rng[1])) if rng
                   else (t("intro_not_found") if known else "—"))
            self.tb_intro.setItem(r, 2, QTableWidgetItem(txt))

    def _save_manual(self):
        a, b = _parse_time(self.ed_a.text()), _parse_time(self.ed_b.text())
        if a is None and b is None:
            ser.store.update(self.series.key, intro=None)
        elif a is None or b is None or b <= a:
            QMessageBox.warning(self, t("tab_intro"), t("intro_bad_range"))
            return
        else:
            ser.store.update(self.series.key, intro=[a, b], intro_off=None)
            self.win.osd(t("intro_saved", a=fmt_time(a), b=fmt_time(b)))
        self._after_intro_change()

    def _reset_intro(self):
        ser.store.update(self.series.key, intro=None, intro_ref=None, intro_auto=None, intro_off=None, auto_skip=None)
        self._after_intro_change()

    def _after_intro_change(self):
        cur = self.win.current
        if cur is not None and self.win._series is not None:
            self.win._intro = ser.store.intro_for(self.win._series, cur.path)
        self._fill_intro()

    def _detect_all(self):
        from . import intro
        paths = [p for p, _ in self.series.episodes]
        ser.store.update(self.series.key, intro=None, intro_ref=None, intro_auto=None, intro_off=None)

        def work(worker):
            def prog(i, n):
                if worker.cancelled:
                    raise InterruptedError
                worker.progress.emit(i, n)
            try:
                return intro.detect(paths, progress=prog)
            except InterruptedError:
                return None

        def finished(res):
            if res is None:
                self._fill_intro()
                return
            ref, ranges = res
            if ref:
                ser.store.update(self.series.key, intro_ref=ref)
            for p in paths:
                ser.store.set_auto(self.series, p, ranges.get(p))
            found = sum(1 for r in ranges.values() if r)
            self._after_intro_change()
            self.win.osd(t("intro_found_n", n=found, m=len(paths)) if found else t("intro_not_found"))
        self._run(work, t("intro_detecting"), len(paths) * 2, finished)
