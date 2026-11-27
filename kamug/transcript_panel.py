"""Sağdaki "Transkript" paneli (YouTube'daki gibi): konuşma ve ekrandaki yazılar, zamana tıklayınca o ana gider.

İşler arka planda yürür (QThread): eksik araç/model indirme → ffmpeg ile ses → whisper.cpp; ya da OCR (screen_text).
Sonuçlar transcript deposuna yazılır; panel kapalıyken de iş sürer, video değişse de kendi dosyasına kaydeder."""
import bisect
import os
import subprocess
import time

from PyQt6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath, QPixmap, QImage
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QMenu,
                             QMessageBox, QProgressBar, QPushButton, QRubberBand, QStackedWidget, QStyle,
                             QStyledItemDelegate, QVBoxLayout, QWidget, QAbstractItemView, QSizePolicy)

from . import screen_text
from . import thumbs
from . import transcript as tr
from . import vlm_ocr
from .config import prefs
from .i18n import t
from .theme import qcolor
from .widgets import Chip, IconButton, Pill

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _fold(text):
    """Türkçeye uygun gevşek arama: İ/I/ı/i aynı sayılır (casefold "İ"yi "i̇" yapıp eşleşmeyi bozuyor)."""
    return text.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")


# ====================================================================== işler
class SpeechJob(QThread):
    """İndir (gerekirse) → ses → whisper. progress(metin, oran -1 = belirsiz), live(segment)."""
    progress = pyqtSignal(str, float)
    live = pyqtSignal(dict)
    reset = pyqtSignal()            # ekran kartı çalışmadı, işlemciyle baştan
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, path, key, duration_ms, translate=False, parent=None):
        super().__init__(parent)
        self.path, self.key, self.duration = path, key, max(0, int(duration_ms or 0))
        self.translate = translate
        self.part = "speech_en" if translate else "speech"
        self._cancel = False
        self._proc = None

    def cancel(self):
        self._cancel = True
        p = self._proc
        if p is not None:
            try:
                p.kill()
            except OSError:
                pass

    def _cancelled(self):
        return self._cancel

    def run(self):
        try:
            self._run()
        except InterruptedError:
            self.failed.emit("cancelled")
        except Exception as e:      # noqa: BLE001 — kullanıcıya gösterilir
            self.failed.emit(str(e) or e.__class__.__name__)

    def _run(self):
        mkey = tr.model_key()
        if self.translate and mkey == "best":
            mkey = "balanced"       # large-v3-turbo çeviri yapamıyor (yalnızca yazıya döker)
        need = tr.missing_downloads(mkey)
        if need:
            total_mb = sum(n[3] for n in need)

            def prog(name, a, b):
                self.progress.emit(t("tr_downloading", name=name, a=f"{a / 1048576:.0f}",
                                     b=f"{(b or 0) / 1048576:.0f}" if b else "?"), (a / b) if b else -1.0)
            self.progress.emit(t("tr_downloading", name="", a="0", b=str(total_mb)), 0.0)
            tr.download_all(mkey, prog, self._cancelled)
        if self._cancel:
            raise InterruptedError
        work = os.path.join(tr.temp_dir(), self.key)
        os.makedirs(work, exist_ok=True)
        wav = os.path.join(work, "audio.wav")
        self.progress.emit(t("tr_extracting"), -1.0)
        self._proc = subprocess.Popen(tr.audio_command(thumbs.FFMPEG, self.path, wav), stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        _o, err = self._proc.communicate()
        if self._cancel:
            raise InterruptedError
        if self._proc.returncode != 0 or not os.path.isfile(wav):
            raise RuntimeError(t("tr_no_audio") + ("\n" + err.decode("utf-8", "replace")[-300:] if err else ""))
        out_base = os.path.join(work, "out")
        try:
            os.remove(out_base + ".json")
        except OSError:
            pass
        gpu = tr.use_gpu()
        self._whisper(wav, out_base, mkey, gpu, work)
        if gpu and not os.path.isfile(out_base + ".json") and not self._cancel:
            self.reset.emit()                   # CUDA açılamadı vb.: işlemciyle tekrar
            self._whisper(wav, out_base, mkey, False, work)
        if self._cancel:
            raise InterruptedError
        if not os.path.isfile(out_base + ".json"):
            try:
                with open(os.path.join(work, "whisper.log"), encoding="utf-8", errors="replace") as f:
                    tail = f.read()[-400:]
            except OSError:
                tail = ""
            raise RuntimeError(t("tr_failed") + ("\n" + tail if tail else ""))
        segs, lang = tr.read_whisper_json(out_base + ".json")
        for n in ("audio.wav", "out.json", "whisper.log"):
            try:
                os.remove(os.path.join(work, n))
            except OSError:
                pass
        data = tr.load(self.key)
        data[self.part] = {"segments": segs, "lang": "en" if self.translate else lang, "model": mkey,
                           "source": "whisper", "created": time.strftime("%Y-%m-%d %H:%M")}
        if self.duration:
            data["duration"] = self.duration
        data["name"] = os.path.basename(self.path)
        tr.save(self.key, data)
        self.finished_ok.emit(data)

    def _whisper(self, wav, out_base, mkey, gpu, work):
        label = t("tr_translating") if self.translate else t("tr_listening")
        if gpu:
            label += "  ·  " + t("tr_gpu_short")
        log = open(os.path.join(work, "whisper.log"), "wb")
        exe_dir = os.path.dirname(tr.whisper_exe(gpu))
        try:
            self._proc = subprocess.Popen(tr.whisper_command(wav, out_base, key=mkey, translate=self.translate,
                                                             gpu=gpu),
                                          stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL,
                                          creationflags=NO_WINDOW, cwd=exe_dir if os.path.isdir(exe_dir) else None)
            self.progress.emit(label, 0.0 if self.duration else -1.0)
            for raw in self._proc.stdout:
                if self._cancel:
                    raise InterruptedError
                seg = tr.parse_live(raw.decode("utf-8", "replace"))
                if seg is None:
                    continue
                a, b, txt = seg
                if txt and not tr._is_noise(txt):
                    self.live.emit({"s": a, "e": b, "t": txt})
                if self.duration:
                    self.progress.emit(label, min(0.99, b / self.duration))
            self._proc.wait()
        finally:
            log.close()


class DiarizeJob(QThread):
    """Konuşmacı ayırma: ses → speakers.diarize → satırlara "spk"."""
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, path, key, part, n_speakers=None, parent=None):
        super().__init__(parent)
        self.path, self.key, self.part, self.n = path, key, part, n_speakers
        self._cancel = False
        self.found = 0

    def cancel(self):
        self._cancel = True

    def run(self):
        from . import speakers
        try:
            work = os.path.join(tr.temp_dir(), self.key)
            os.makedirs(work, exist_ok=True)
            wav = os.path.join(work, "spk.wav")
            self.progress.emit(t("tr_extracting"), -1.0)
            r = subprocess.run(tr.audio_command(thumbs.FFMPEG, self.path, wav), capture_output=True,
                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            if self._cancel:
                raise InterruptedError
            if r.returncode != 0 or not os.path.isfile(wav):
                raise RuntimeError(t("tr_no_audio"))
            self.progress.emit(t("tr_spk_working"), -1.0)
            data = tr.load(self.key)
            segs = (data.get(self.part) or {}).get("segments") or []
            self.found = speakers.diarize(wav, segs, self.n)
            try:
                os.remove(wav)
            except OSError:
                pass
            if self._cancel:
                raise InterruptedError
            data[self.part]["speakers"] = self.found
            tr.save(self.key, data)
            self.finished_ok.emit(data)
        except InterruptedError:
            self.failed.emit("cancelled")
        except Exception as e:      # noqa: BLE001
            self.failed.emit(str(e) or e.__class__.__name__)


class OcrJob(QThread):
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, path, key, duration_ms, region=None, engine="windows", parent=None):
        super().__init__(parent)
        self.path, self.key, self.duration, self.region = path, key, max(0, int(duration_ms or 0)), region
        self.engine = engine            # windows | vlm (gelişmiş okuma)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        vlm = self.engine == "vlm"
        if vlm:     # sayfa okumak taramadan çok daha uzun sürer
            stages = {"scan": (t("ocr_scanning"), 0.0, 0.10), "frames": (t("ocr_frames"), 0.10, 0.05),
                      "ocr": (t("ocr_vlm_reading"), 0.15, 0.85)}
        else:
            stages = {"scan": (t("ocr_scanning"), 0.0, 0.45), "frames": (t("ocr_frames"), 0.45, 0.25),
                      "ocr": (t("ocr_reading"), 0.70, 0.30)}

        def prog(stage, r):
            label, a, w = stages[stage]
            self.progress.emit(label, a + w * max(0.0, min(1.0, r)))
        try:
            reader = None
            if vlm:
                if vlm_ocr.missing_downloads():
                    def dl(name, done, total):
                        self.progress.emit(t("tr_downloading", name=name, a=f"{done / 1048576:.0f}",
                                             b=f"{total / 1048576:.0f}" if total else "?"),
                                           done / total if total else -1.0)
                    vlm_ocr.download_all(dl, lambda: self._cancel)
                reader = vlm_ocr.read_files
            frames = screen_text.run(thumbs.FFMPEG, self.path, tr.frames_dir(self.key), self.region,
                                     (self.duration / 1000.0) or None, lambda: self._cancel, prog, reader)
        except InterruptedError:
            self.failed.emit("cancelled")
            return
        except RuntimeError as e:
            self.failed.emit(t("ocr_no_language") if str(e) == "no-ocr-language" else str(e))
            return
        except Exception as e:      # noqa: BLE001
            self.failed.emit(str(e) or e.__class__.__name__)
            return
        data = tr.load(self.key)
        data["ocr"] = {"frames": frames, "region": list(self.region) if self.region else None,
                       "engine": self.engine, "created": time.strftime("%Y-%m-%d %H:%M")}
        if self.duration:
            data["duration"] = self.duration
        data["name"] = os.path.basename(self.path)
        tr.save(self.key, data)
        self.finished_ok.emit(data)


# ====================================================================== liste
class RowModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []          # {"s", "t", "img"?}
        self.current = -1
        self.img_dir = ""
        self.math = False       # gelişmiş okuma: $LaTeX$ okunur gösterilir (kayıtta LaTeX kalır)
        self._pix = {}

    def text(self, row):
        s = row.get("t", "")
        return vlm_ocr.to_display(s) if self.math and "$" in s or self.math and "**" in s else s

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return r
        if role == Qt.ItemDataRole.DisplayRole:
            return r.get("t", "")
        return None

    def set_rows(self, rows, img_dir=""):
        self.beginResetModel()
        self.rows = list(rows)
        self.img_dir = img_dir
        self.current = -1
        self._pix = {}
        self.endResetModel()

    def append(self, row):
        n = len(self.rows)
        self.beginInsertRows(QModelIndex(), n, n)
        self.rows.append(row)
        self.endInsertRows()

    def pixmap(self, name, width):
        k = (name, width)
        pm = self._pix.get(k)
        if pm is None:
            img = QImage(os.path.join(self.img_dir, name))
            pm = QPixmap.fromImage(img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)) \
                if not img.isNull() else QPixmap()
            self._pix[k] = pm
        return pm


class RowDelegate(QStyledItemDelegate):
    PAD = 10
    CHIP_W = 64

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.font = QFont(QApplication.font())
        self.font.setPixelSize(14)
        self.chip_font = QFont(QApplication.font())
        self.chip_font.setPixelSize(12)
        self.chip_font.setWeight(QFont.Weight.DemiBold)

    def _text_rect(self, width):
        return QRect(0, 0, max(40, width - self.CHIP_W - self.PAD * 3), 100000)

    def _img_h(self, row, width):
        if not row.get("img"):
            return 0
        pm = self.model.pixmap(row["img"], max(40, width - self.CHIP_W - self.PAD * 3))
        return 0 if pm.isNull() else pm.height() + 8

    def _speaker(self, index, row):
        """Konuşmacı değiştiyse (ya da ilk satırsa) adı; yoksa None."""
        spk = row.get("spk")
        if not spk:
            return None
        i = index.row()
        prev = self.model.rows[i - 1].get("spk") if i > 0 else None
        return tr.speaker_name(spk) if spk != prev else None

    def sizeHint(self, option, index):
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        w = option.rect.width() or 360
        fm = QFontMetrics(self.font)
        br = fm.boundingRect(self._text_rect(w), Qt.TextFlag.TextWordWrap, self.model.text(row) or " ")
        extra = 22 if self._speaker(index, row) else 0
        return QSize(w, max(34, br.height() + self._img_h(row, w) + 16) + extra)

    def paint(self, p, option, index):
        row = index.data(Qt.ItemDataRole.UserRole) or {}
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        cur = index.row() == self.model.current
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if cur or hov:
            path = QPainterPath()
            path.addRoundedRect(QRectF(r.adjusted(2, 1, -2, -1)), 10, 10)
            p.fillPath(path, qcolor("selected" if cur else "hover"))
        chip = QRectF(r.left() + self.PAD, r.top() + 8, self.CHIP_W - 6, 20)
        x = r.left() + self.PAD * 2 + self.CHIP_W
        y = r.top() + 8
        tw = max(40, r.width() - self.CHIP_W - self.PAD * 3)
        name = self._speaker(index, row)
        if name:
            p.setFont(self.chip_font)
            p.setPen(qcolor("text2"))
            p.drawText(QRect(x, y, tw, 20), Qt.AlignmentFlag.AlignVCenter, name)
            y += 22
            chip.moveTop(chip.top() + 22)
        if row.get("img"):
            pm = self.model.pixmap(row["img"], tw)
            if not pm.isNull():
                clip = QPainterPath()
                clip.addRoundedRect(QRectF(x, y, pm.width(), pm.height()), 8, 8)
                p.save()
                p.setClipPath(clip)
                p.drawPixmap(x, y, pm)
                p.restore()
                y += pm.height() + 8
        cp = QPainterPath()
        cp.addRoundedRect(chip, 6, 6)
        p.fillPath(cp, qcolor("surface_hover" if cur else "surface"))
        p.setFont(self.chip_font)
        p.setPen(qcolor("text"))
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, tr.fmt_ts(row.get("s", 0)))
        p.setFont(self.font)
        p.setPen(qcolor("text"))
        p.drawText(QRect(x, y - 1, tw, r.bottom() - y), Qt.TextFlag.TextWordWrap, self.model.text(row))
        p.restore()


class RowView(QListView):
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.scheduleDelayedItemsLayout()     # satır yükseklikleri genişliğe bağlı


# ====================================================================== bölge seçimi
class RegionDialog(QDialog):
    """Karenin üstünde fareyle dikdörtgen çizilir → (x, y, w, h) 0-1 arası; Tüm ekran → None."""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("ocr_region_title"))
        self.region = None
        img = QPixmap(image_path)
        scr = self.screen().availableGeometry() if self.screen() else QRect(0, 0, 1280, 800)
        maxw, maxh = int(scr.width() * 0.8), int(scr.height() * 0.7)
        if not img.isNull() and (img.width() > maxw or img.height() > maxh):
            img = img.scaled(maxw, maxh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        lay = QVBoxLayout(self)
        hint = QLabel(t("ocr_region_hint"))
        hint.setObjectName("Secondary")
        lay.addWidget(hint)
        self.lbl = QLabel()
        self.lbl.setPixmap(img)
        self.lbl.setFixedSize(img.size())
        self.lbl.setCursor(Qt.CursorShape.CrossCursor)
        self.lbl.installEventFilter(self)
        lay.addWidget(self.lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.band = QRubberBand(QRubberBand.Shape.Rectangle, self.lbl)
        self._origin = None
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_all = QPushButton(t("ocr_whole_screen"))
        self.btn_all.clicked.connect(lambda: (setattr(self, "region", None), self.accept()))
        self.btn_ok = QPushButton(t("ocr_use_region"))
        self.btn_ok.setEnabled(False)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        for b in (self.btn_all, self.btn_ok, cancel):
            b.setObjectName("Pill")
            b.setFixedHeight(32)
            row.addWidget(b)
        lay.addLayout(row)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.lbl:
            if ev.type() == QEvent.Type.MouseButtonPress:
                self._origin = ev.position().toPoint()
                self.band.setGeometry(QRect(self._origin, QSize()))
                self.band.show()
                return True
            if ev.type() == QEvent.Type.MouseMove and self._origin is not None:
                self.band.setGeometry(QRect(self._origin, ev.position().toPoint()).normalized()
                                      .intersected(self.lbl.rect()))
                return True
            if ev.type() == QEvent.Type.MouseButtonRelease and self._origin is not None:
                self._origin = None
                g = self.band.geometry()
                W, H = self.lbl.width(), self.lbl.height()
                if g.width() > 8 and g.height() > 8 and W and H:
                    self.region = (g.x() / W, g.y() / H, g.width() / W, g.height() / H)
                    self.btn_ok.setEnabled(True)
                return True
        return super().eventFilter(obj, ev)


# ====================================================================== panel
class TranscriptPanel(QWidget):
    seek = pyqtSignal(int)
    close_clicked = pyqtSignal()

    TAB_SPEECH, TAB_EN, TAB_OCR = "speech", "speech_en", "ocr"
    _jobs = {}              # (anahtar, sekme) → iş (pencere başına tek panel, sınıf düzeyi yeterli)

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.item = None
        self.key = None
        self.data = {}
        self.tab = self.TAB_SPEECH
        self._live = []
        self._user_scroll = 0.0
        self._starts = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 8, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(8, 6, 0, 0)
        self.lbl_title = QLabel(t("tr_title"))
        self.lbl_title.setObjectName("SectionTitle")
        head.addWidget(self.lbl_title, 1)
        self.btn_yazit = IconButton("open_in", t("tr_open_yazit"), 36, 20)
        self.btn_yazit.clicked.connect(self.open_in_yazit)
        self.btn_more = IconButton("more", t("more"), 36, 20)
        self.btn_more.clicked.connect(self._menu)
        self.btn_close = IconButton("close", t("hide_panel"), 36, 20)
        self.btn_close.clicked.connect(self.close_clicked.emit)
        for b in (self.btn_yazit, self.btn_more, self.btn_close):
            head.addWidget(b)
        lay.addLayout(head)

        chips = QHBoxLayout()
        chips.setContentsMargins(8, 4, 0, 0)
        chips.setSpacing(8)
        self.chip_speech = Chip(t("tr_speech"))
        self.chip_en = Chip(t("tr_english"))
        self.chip_ocr = Chip(t("tr_screen"))
        self.chip_speech.clicked.connect(lambda: self.set_tab(self.TAB_SPEECH))
        self.chip_en.clicked.connect(lambda: self.set_tab(self.TAB_EN))
        self.chip_ocr.clicked.connect(lambda: self.set_tab(self.TAB_OCR))
        chips.addWidget(self.chip_speech)
        chips.addWidget(self.chip_en)
        chips.addWidget(self.chip_ocr)
        chips.addStretch(1)
        lay.addLayout(chips)

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("tr_search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._fill())
        lay.addWidget(self.search)

        self.pages = QStackedWidget()
        lay.addWidget(self.pages, 1)
        # boş durum
        self.page_empty = QWidget()
        el = QVBoxLayout(self.page_empty)
        el.setContentsMargins(12, 24, 12, 12)
        el.setSpacing(10)
        self.lbl_empty = QLabel()
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setObjectName("Secondary")
        el.addWidget(self.lbl_empty)
        self.btn_start = Pill("  " + t("tr_start"), "play")
        self.btn_start.clicked.connect(self._start_clicked)
        el.addWidget(self.btn_start)
        self.btn_region = Pill("  " + t("ocr_pick_region"), "crop")
        self.btn_region.clicked.connect(lambda: self.start_ocr(pick_region=True))
        el.addWidget(self.btn_region)
        self.btn_alt = Pill("  " + t("ocr_vlm"), "edit")    # tercih edilmeyen diğer okuma yolu
        self.btn_alt.clicked.connect(lambda: self.start_ocr(engine=self._alt_engine()))
        el.addWidget(self.btn_alt)
        self.btn_subs = Pill("  " + t("tr_use_subs"), "subtitles")
        self.btn_subs.clicked.connect(self.use_subtitles)
        el.addWidget(self.btn_subs)
        self.lbl_model = QLabel()
        self.lbl_model.setWordWrap(True)
        self.lbl_model.setObjectName("Secondary")
        el.addWidget(self.lbl_model)
        el.addStretch(1)
        self.pages.addWidget(self.page_empty)
        # liste (+ iş sürerken üstte ilerleme)
        self.page_list = QWidget()
        ll = QVBoxLayout(self.page_list)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        self.prog_box = QWidget()
        pl = QVBoxLayout(self.prog_box)
        pl.setContentsMargins(8, 4, 8, 4)
        pl.setSpacing(4)
        prow = QHBoxLayout()
        self.lbl_prog = QLabel()
        self.lbl_prog.setObjectName("Secondary")
        self.lbl_prog.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        prow.addWidget(self.lbl_prog, 1)
        self.btn_cancel = QPushButton(t("cancel"))
        self.btn_cancel.setObjectName("Pill")
        self.btn_cancel.setFixedHeight(28)
        self.btn_cancel.clicked.connect(self.cancel_job)
        prow.addWidget(self.btn_cancel)
        pl.addLayout(prow)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        pl.addWidget(self.bar)
        ll.addWidget(self.prog_box)
        self.model = RowModel(self)
        self.view = RowView()
        self.view.setObjectName("UpNext")
        self.view.setModel(self.model)
        self.view.setItemDelegate(RowDelegate(self.model, self.view))
        self.view.setMouseTracking(True)
        self.view.setWordWrap(True)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.verticalScrollBar().setSingleStep(24)
        self.view.clicked.connect(self._row_clicked)
        self.view.verticalScrollBar().sliderPressed.connect(self._touched)
        self.view.viewport().installEventFilter(self)
        ll.addWidget(self.view, 1)
        self.lbl_none = QLabel()
        self.lbl_none.setObjectName("Secondary")
        self.lbl_none.setWordWrap(True)
        self.lbl_none.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.lbl_none)
        self.pages.addWidget(self.page_list)
        self._update_chips()

    # ------------------------------------------------------------------ durum
    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.view.viewport() and ev.type() == QEvent.Type.Wheel:
            self._touched()
        return super().eventFilter(obj, ev)

    def _touched(self):
        self._user_scroll = time.monotonic()

    def _update_chips(self):
        self.chip_speech.setChecked(self.tab == self.TAB_SPEECH)
        self.chip_en.setChecked(self.tab == self.TAB_EN)
        self.chip_ocr.setChecked(self.tab == self.TAB_OCR)
        en = bool((self.data.get(self.TAB_EN) or {}).get("segments")) or \
            (self.key is not None and self._running(self.TAB_EN) is not None)
        self.chip_en.setVisible(en)
        if not en and self.tab == self.TAB_EN:
            self.tab = self.TAB_SPEECH
            self.chip_speech.setChecked(True)

    def _speechy(self, tab=None):
        return (tab or self.tab) in (self.TAB_SPEECH, self.TAB_EN)

    def _running(self, tab):
        j = self._jobs.get((self.key, tab))
        return j if j is not None and j.isRunning() else None

    def set_tab(self, tab):
        self.tab = tab
        self._update_chips()
        self.refresh()

    def set_item(self, item):
        """Açık dosya değişti. Panel görünür değilse anahtar hesaplanmaz (dosya okunmasın)."""
        if item is not None and (not item.is_playable or item.is_stream):
            item = None
        same = item is not None and self.item is not None and os.path.normcase(item.path) == \
            os.path.normcase(self.item.path)
        self.item = item
        if not same:
            self.key = None
            self.data = {}
            self._live = []
        if self.isVisible():
            self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def _ensure_key(self):
        if self.item is not None and self.key is None:
            self.key = tr.file_key(self.item.path)
            self.data = tr.load(self.key)
        return self.key

    def _duration(self):
        d = self.item.duration if self.item is not None else -1
        if (not d or d <= 0) and self.win.engine is not None and self.win.current is self.item:
            d = self.win.engine.get_length()
        return max(0, int(d or 0))

    def _job(self):
        if self.key is None:
            return None
        return self._running(self.tab)

    def refresh(self):
        self._ensure_key()
        self._update_chips()
        enabled_audio = self.item is not None and self.item.is_audio
        self.chip_ocr.setVisible(not enabled_audio)
        if enabled_audio and self.tab == self.TAB_OCR:
            self.tab = self.TAB_SPEECH
            self._update_chips()
        job = self._job()
        part = self.data.get(self.tab) or {}
        has = bool(part.get("segments") or part.get("frames"))
        self.btn_yazit.setVisible(any(self.data.get(k) for k in tr.PARTS))
        self.search.setVisible(has)
        if self.item is None:
            self._show_empty(t("tr_no_media"))
            return
        if job is not None:
            self.pages.setCurrentWidget(self.page_list)
            self.prog_box.show()
            if isinstance(job, SpeechJob):
                self.model.set_rows(self._live)
            elif isinstance(job, DiarizeJob):
                self.model.set_rows(self._rows())
            else:
                self.model.set_rows([])
            self._after_fill()
            return
        self.prog_box.hide()
        if not has:
            if self._speechy():
                self._show_empty(t("tr_empty_speech"))
            else:
                self._show_empty(t("ocr_empty"))
            return
        self.pages.setCurrentWidget(self.page_list)
        self._fill()

    def _show_empty(self, text):
        self.pages.setCurrentWidget(self.page_empty)
        self.lbl_empty.setText(text)
        sp = self._speechy()
        has_item = self.item is not None
        self.btn_start.setVisible(has_item)
        self.btn_start.setText("  " + (t("tr_start") if sp else t("ocr_start")))
        self.btn_region.setVisible(has_item and not sp)
        self.btn_alt.setVisible(has_item and not sp)
        self.btn_alt.setText("  " + t("ocr_vlm" if self._alt_engine() == "vlm" else "ocr_fast"))
        self.btn_subs.setVisible(has_item and sp and self._has_subs())
        if sp and has_item:
            k = tr.model_key()
            missing = tr.missing_downloads(k)
            info = t("tr_model_info", model=t("tr_model_" + k))
            if missing:
                info += "\n" + t("tr_first_download", mb=sum(m[3] for m in missing))
            self.lbl_model.setText(info)
        elif has_item:
            if self._engine() == "vlm":
                info = t("ocr_vlm_info")
                if vlm_ocr.missing_downloads():
                    info += "\n" + t("ocr_vlm_download", mb=sum(m[3] for m in vlm_ocr.missing_downloads()))
            else:
                info = t("ocr_info")
            self.lbl_model.setText(info)
        else:
            self.lbl_model.setText("")

    def _has_subs(self):
        if self.item is None:
            return False
        if tr.sidecar_subtitle(self.item.path):
            return True
        e = self.win.engine
        try:   # sub_tracks() "Devre dışı" girişini de içerir
            return bool(e is not None and self.win.current is self.item and
                        any(i >= 0 for i, _ in e.sub_tracks()))
        except Exception:
            return False

    def _rows(self):
        part = self.data.get(self.tab) or {}
        if self._speechy():
            return part.get("segments") or []
        return part.get("frames") or []

    def _fill(self):
        rows = self._rows()
        q = _fold(self.search.text().strip())
        if q:
            rows = [r for r in rows if q in _fold(r.get("t") or "")]
        self.model.math = not self._speechy() and (self.data.get(self.TAB_OCR) or {}).get("engine") == "vlm"
        self.model.set_rows(rows, tr.frames_dir(self.key) if self.key else "")
        self._after_fill()
        if q and not rows:
            self.lbl_none.setText(t("tr_no_match"))
            self.lbl_none.show()

    def _after_fill(self):
        self._starts = [r.get("s", 0) for r in self.model.rows]
        self.lbl_none.hide()
        if self.win.engine is not None and self.win.current is self.item and self.item is not None:
            self.set_time(int(self.win.engine.get_time()), force=True)

    # ------------------------------------------------------------------ zaman senkronu
    def set_time(self, ms, force=False):
        if not self._starts:
            return
        i = bisect.bisect_right(self._starts, ms + 150) - 1
        if i == self.model.current and not force:
            return
        old = self.model.current
        self.model.current = i
        for k in (old, i):
            if 0 <= k < len(self.model.rows):
                idx = self.model.index(k)
                self.view.update(idx)
        if i >= 0 and time.monotonic() - self._user_scroll > 4 and not self.search.text():
            self.view.scrollTo(self.model.index(i), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _row_clicked(self, index):
        r = index.data(Qt.ItemDataRole.UserRole)
        if r is not None:
            self._user_scroll = 0.0
            self.seek.emit(int(r.get("s", 0)))

    # ------------------------------------------------------------------ işler
    def _start_clicked(self):
        if self._speechy():
            self.start_speech(translate=self.tab == self.TAB_EN)
        else:
            self.start_ocr()

    def start_speech(self, translate=False):
        if self.item is None or self._ensure_key() is None:
            return
        tab = self.TAB_EN if translate else self.TAB_SPEECH
        if self._running(tab) is not None:
            return
        k = tr.model_key()
        if translate and k == "best":
            k = "balanced"
        missing = tr.missing_downloads(k)
        if missing:
            mb = sum(m[3] for m in missing)
            r = QMessageBox.question(self, t("tr_title"), t("tr_download_ask", mb=mb, model=t("tr_model_" + k)))
            if r != QMessageBox.StandardButton.Yes:
                return
        job = SpeechJob(self.item.path, self.key, self._duration(), translate, self)
        key = self.key
        self._live = []
        job.progress.connect(lambda txt, r, k=key, tb=tab: self._on_progress(k, tb, txt, r))
        job.live.connect(lambda seg, k=key, tb=tab: self._on_live(k, tb, seg))
        job.reset.connect(lambda k=key, tb=tab: self._on_reset(k, tb))
        job.finished_ok.connect(lambda d, k=key, tb=tab: self._on_done(k, d, tb))
        job.failed.connect(lambda m, k=key, tb=tab: self._on_failed(k, m, tb))
        self._jobs[(key, tab)] = job
        self.tab = tab
        job.start()
        self.refresh()
        self._on_progress(key, tab, t("tr_preparing"), -1.0)

    def start_diarize(self, n=None):
        if self.item is None or self._ensure_key() is None or not self._speechy():
            return
        tab = self.tab
        if self._running(tab) is not None or not self._rows():
            return
        job = DiarizeJob(self.item.path, self.key, tab, n, self)
        key = self.key
        job.progress.connect(lambda txt, r, k=key, tb=tab: self._on_progress(k, tb, txt, r))
        job.finished_ok.connect(lambda d, k=key, tb=tab, j=job: (self._on_done(k, d, tb),
                                                                 self.win.osd(t("tr_spk_found", n=j.found))))
        job.failed.connect(lambda m, k=key, tb=tab: self._on_failed(k, m, tb))
        self._jobs[(key, tab)] = job
        job.start()
        self.refresh()

    def clear_speakers(self):
        part = self.data.get(self.tab) or {}
        for s in part.get("segments") or []:
            s.pop("spk", None)
        part.pop("speakers", None)
        tr.save(self.key, self.data)
        self.refresh()

    def _engine(self):
        return "vlm" if prefs.get("ocr_engine") == "vlm" else "windows"

    def _alt_engine(self):
        return "windows" if self._engine() == "vlm" else "vlm"

    def start_ocr(self, pick_region=False, engine=None):
        if self.item is None or self._ensure_key() is None or not self.item.is_video:
            return
        if self._running(self.TAB_OCR) is not None:
            return
        engine = engine or self._engine()
        if engine == "vlm" and vlm_ocr.missing_downloads():
            mb = sum(m[3] for m in vlm_ocr.missing_downloads())
            if QMessageBox.question(self.win, t("ocr_vlm"), t("ocr_vlm_confirm", mb=mb)) != \
                    QMessageBox.StandardButton.Yes:
                return
        region = None
        if pick_region:
            region = self._pick_region()
            if region is False:
                return
        job = OcrJob(self.item.path, self.key, self._duration(), region, engine, self)
        key = self.key
        job.progress.connect(lambda txt, r, k=key: self._on_progress(k, self.TAB_OCR, txt, r))
        job.finished_ok.connect(lambda d, k=key: self._on_done(k, d, self.TAB_OCR))
        job.failed.connect(lambda m, k=key: self._on_failed(k, m, self.TAB_OCR))
        self._jobs[(key, self.TAB_OCR)] = job
        self.tab = self.TAB_OCR
        job.start()
        self.refresh()
        self._on_progress(key, self.TAB_OCR, t("ocr_scanning"), 0.0)

    def _pick_region(self):
        """Şimdiki kareyi gösterip bölge seçtirir. Döndürür: bölge | None (tüm ekran) | False (vazgeçildi)."""
        sec = 0.0
        if self.win.engine is not None and self.win.current is self.item:
            sec = max(0.0, self.win.engine.get_time() / 1000.0)
        dest = os.path.join(tr.temp_dir(), "region.jpg")
        try:
            os.remove(dest)
        except OSError:
            pass
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = screen_text.extract_frame(thumbs.FFMPEG, self.item.path, sec, dest, None, 1280)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            return None
        d = RegionDialog(dest, self.win)
        if d.exec() != QDialog.DialogCode.Accepted:
            return False
        return d.region

    def cancel_job(self):
        if self.key is None:
            return
        j = self._jobs.get((self.key, self.tab))
        if j is not None:
            j.cancel()

    def _on_progress(self, key, tab, text, ratio):
        if key != self.key or tab != self.tab:
            return
        self.prog_box.show()
        self.lbl_prog.setText(text + (f"  ·  %{int(ratio * 100)}" if ratio >= 0 else ""))
        if ratio < 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(ratio * 1000))

    def _on_reset(self, key, tab):
        if key == self.key:
            self._live = []
            if tab == self.tab:
                self.model.set_rows([])
                self._starts = []

    def _on_live(self, key, tab, seg):
        if key != self.key:
            return
        self._live.append(seg)
        if self.tab == tab and self.pages.currentWidget() is self.page_list and not self.search.text():
            self.model.append(seg)
            self._starts.append(seg["s"])
            if time.monotonic() - self._user_scroll > 4:
                self.view.scrollToBottom()

    def _on_done(self, key, data, tab):
        self._jobs.pop((key, tab), None)
        if key != self.key:
            return
        self.data = data
        self._live = []
        if self._speechy(tab) and not (data.get(tab) or {}).get("segments"):
            self.win.osd(t("tr_nothing_heard"))
        elif tab == self.TAB_OCR and not (data.get("ocr") or {}).get("frames"):
            self.win.osd(t("ocr_nothing"))
        if tab == self.tab:
            self.refresh()
        else:
            self.btn_yazit.setVisible(True)

    def _on_failed(self, key, msg, tab):
        self._jobs.pop((key, tab), None)
        if key == self.key:
            self._live = []
            self.refresh()
        if msg != "cancelled":
            QMessageBox.warning(self.win, t("tr_title"), msg)

    def use_subtitles(self):
        if self.item is None or self._ensure_key() is None:
            return
        key, path, dur = self.key, self.item.path, self._duration()

        def done(res):
            segs, src = res
            if not segs:
                QMessageBox.information(self.win, t("tr_title"), t("tr_subs_none"))
                return
            data = tr.load(key)
            data["speech"] = {"segments": segs, "source": src or "subtitle",
                              "created": time.strftime("%Y-%m-%d %H:%M")}
            if dur:
                data["duration"] = dur
            data["name"] = os.path.basename(path)
            tr.save(key, data)
            if key == self.key:
                self.data = data
                self.refresh()
        thumbs.run_async(tr.from_subtitles, thumbs.FFMPEG, path, on_done=done,
                         on_fail=lambda m: QMessageBox.warning(self.win, t("tr_title"), m))

    # ------------------------------------------------------------------ menü / dışa aktarma
    def _menu(self):
        m = QMenu(self)
        sp = self._speechy()
        segs = (self.data.get(self.tab) or {}).get("segments") or [] if sp else []
        frames = [] if sp else (self.data.get(self.TAB_OCR) or {}).get("frames") or []
        has_any = any(self.data.get(k) for k in tr.PARTS)
        busy = self._job() is not None
        a_delta = m.addAction(t("tr_save_yazit"))
        a_delta.setEnabled(has_any)
        a_srt = m.addAction(t("tr_save_srt"))
        a_txt = m.addAction(t("tr_save_txt"))
        a_copy = m.addAction(t("tr_copy"))
        a_srt.setEnabled(bool(segs) and sp)
        for a in (a_txt, a_copy):
            a.setEnabled(bool(segs) or bool(frames))
        m.addSeparator()
        a_redo = m.addAction(t("tr_redo") if sp else t("ocr_redo"))
        a_redo.setEnabled(self.item is not None and not busy)
        a_region = None
        if not sp:
            a_region = m.addAction(t("ocr_pick_region"))
            a_region.setEnabled(self.item is not None and not busy)
            a_alt = m.addAction(t("ocr_vlm" if self._alt_engine() == "vlm" else "ocr_fast"))
            a_alt.setEnabled(self.item is not None and not busy)
        else:
            a_alt = None
        a_subs = None
        if self.tab == self.TAB_SPEECH and self._has_subs():
            a_subs = m.addAction(t("tr_use_subs"))
            a_subs.setEnabled(not busy)
        a_en = a_clear = None
        spk_acts = {}
        if sp:
            if self.tab == self.TAB_SPEECH:
                a_en = m.addAction(t("tr_translate_en"))
                a_en.setEnabled(self.item is not None and self._running(self.TAB_EN) is None)
            sm = m.addMenu(t("tr_spk_menu"))
            sm.setEnabled(bool(segs) and not busy)
            for n in (None, 2, 3, 4):
                spk_acts[sm.addAction(t("tr_spk_auto") if n is None else t("tr_spk_n_people", n=n))] = n
            if any(s.get("spk") for s in segs):
                sm.addSeparator()
                a_clear = sm.addAction(t("tr_spk_clear"))
        a_del = m.addAction(t("tr_delete"))
        a_del.setEnabled(bool(self.data.get(self.tab)) and not busy)
        m.addSeparator()
        a_prefs = m.addAction(t("tr_settings"))
        a = m.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height())))
        if a is None:
            return
        if a is a_delta:
            self.save_yazit_as()
        elif a is a_srt:
            self._save_text("srt", tr.to_srt(segs))
        elif a is a_txt:
            self._save_text("txt", tr.to_txt(segs) if sp else tr.frames_txt(frames))
        elif a is a_copy:
            QApplication.clipboard().setText(tr.to_txt(segs, stamps=False) if sp else
                                             tr.frames_txt(frames, stamps=False))
            self.win.osd(t("copied"))
        elif a is a_alt:
            self.start_ocr(engine=self._alt_engine())
        elif a is a_redo:
            self._start_clicked()
        elif a is a_region:
            self.start_ocr(pick_region=True)
        elif a is a_subs:
            self.use_subtitles()
        elif a is a_en:
            self.start_speech(translate=True)
        elif a in spk_acts:
            self.start_diarize(spk_acts[a])
        elif a is a_clear:
            self.clear_speakers()
        elif a is a_del:
            tr.remove(self.key, self.tab)
            self.data = tr.load(self.key)
            self.refresh()
        elif a is a_prefs:
            from .dialogs import PreferencesDialog
            PreferencesDialog(self.win, "transcript").exec()
            self.refresh()

    def _base_name(self):
        return os.path.splitext(self.item.path)[0] if self.item is not None else "transcript"

    def _save_text(self, ext, text):
        path, _ = QFileDialog.getSaveFileName(self, t("tr_title"), f"{self._base_name()}.{ext}",
                                              f"{ext.upper()} (*.{ext})")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig" if ext == "srt" else "utf-8") as f:
                f.write(text)
            self.win.osd(t("saved_to", p=path))
        except OSError as e:
            QMessageBox.warning(self, t("tr_title"), str(e))

    def save_yazit_as(self):
        from . import yazit_export as dx
        if self.item is None or not self.data:
            return
        start = os.path.join(dx.notes_root(), "kamug", os.path.basename(self._base_name()) + dx.NOTE_EXT)
        os.makedirs(os.path.dirname(start), exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, t("tr_save_yazit"), start, f"yazıt (*{dx.NOTE_EXT})")
        if not path:
            return
        try:
            dx.save_note(self.item.path, self.data, self.key, path)
            self.win.osd(t("saved_to", p=path))
        except OSError as e:
            QMessageBox.warning(self, t("tr_title"), str(e))

    def open_in_yazit(self):
        from . import yazit_export as dx
        if self.item is None or not self.data:
            return
        exe = dx.find_yazit()
        if not exe:
            QMessageBox.information(self, t("tr_title"), t("tr_no_yazit"))
            self.save_yazit_as()
            return
        try:
            path = dx.save_note(self.item.path, self.data, self.key)
        except OSError as e:
            QMessageBox.warning(self, t("tr_title"), str(e))
            return
        if dx.open_in_yazit(path):
            self.win.osd(t("tr_opened_yazit"))
        else:
            QMessageBox.warning(self, t("tr_title"), t("tr_yazit_failed"))

    def shutdown(self):
        for j in list(self._jobs.values()):
            j.cancel()
            j.wait(3000)
