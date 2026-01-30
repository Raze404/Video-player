import json
import os
import platform
import random
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    import vlc
except Exception:
    vlc = None


VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
    ".m4v",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts",
    ".mts",
    ".vob",
    ".asf",
    ".mpe",
    ".mp2",
    ".mpv",
    ".f4v",
    ".divx",
    ".xvid",
    ".ogm",
    ".rm",
    ".rmvb",
    ".qt",
    ".m1v",
    ".m2v",
    ".m3u8",
    ".h264",
    ".hevc",
    ".mxf",
    ".dv",
    ".drc",
    ".nsv",
    ".yuv",
    ".amv",
    ".avchd",
    ".gifv",
    ".m2p",
    ".m2t",
    ".mp4v",
    ".3g2",
    ".m4p",
    ".m4b",
    ".m4r",
    ".m4a",
    ".ogx",
    ".mka",
    ".mks",
    ".mk3d",
}

APP_NAME = "DarkVLCPlayer"


def _cfg_path() -> str:
    base = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation)
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "config.json")


def _load_cfg() -> Dict[str, Any]:
    p = _cfg_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cfg(cfg: Dict[str, Any]) -> None:
    p = _cfg_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _norm(p: str) -> str:
    try:
        return os.path.abspath(p)
    except Exception:
        return p


@dataclass
class VideoItem:
    path: str
    name: str
    rel: str
    folder: str
    size: int


def _scan(root_folder: str) -> List[VideoItem]:
    root = _norm(root_folder)
    out: List[VideoItem] = []

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in VIDEO_EXTS:
                continue

            full = _norm(os.path.join(dirpath, fn))
            rel = os.path.relpath(full, root)
            folder = os.path.dirname(rel)

            try:
                size = os.path.getsize(full)
            except Exception:
                size = 0

            out.append(VideoItem(path=full, name=fn, rel=rel, folder=folder, size=size))

    out.sort(key=lambda x: (x.folder.lower(), x.name.lower()))
    return out


def _fmt_ms(ms: int) -> str:
    if ms is None or ms < 0:
        return "00:00"
    sec = ms // 1000
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def _fmt_bytes(n: int) -> str:
    try:
        v = float(n)
        for u in ["B", "KB", "MB", "GB", "TB"]:
            if v < 1024.0 or u == "TB":
                return f"{v:.1f}{u}" if u != "B" else f"{int(v)}B"
            v /= 1024.0
    except Exception:
        return "0B"
    return "0B"


class ClickableSlider(QtWidgets.QSlider):
    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
        if e.button() == QtCore.Qt.LeftButton:
            opt = QtWidgets.QStyleOptionSlider()
            self.initStyleOption(opt)

            groove = self.style().subControlRect(
                QtWidgets.QStyle.CC_Slider,
                opt,
                QtWidgets.QStyle.SC_SliderGroove,
                self,
            )
            handle = self.style().subControlRect(
                QtWidgets.QStyle.CC_Slider,
                opt,
                QtWidgets.QStyle.SC_SliderHandle,
                self,
            )

            if self.orientation() == QtCore.Qt.Horizontal:
                x = e.pos().x()
                x = max(groove.left(), min(x, groove.right()))

                slider_min = groove.left()
                slider_max = groove.right() - handle.width() + 1

                if slider_max <= slider_min:
                    val = self.minimum()
                else:
                    ratio = (x - slider_min) / (slider_max - slider_min)
                    val = self.minimum() + ratio * (self.maximum() - self.minimum())

                self.setValue(int(val))
                self.sliderMoved.emit(self.value())
                self.sliderPressed.emit()
                self.sliderReleased.emit()
                e.accept()
                return

        super().mousePressEvent(e)


class VideoSurface(QtWidgets.QFrame):
    doubleClicked = QtCore.pyqtSignal()

    def mouseDoubleClickEvent(self, e: QtGui.QMouseEvent) -> None:
        if e.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)


class DropMainWindow(QtWidgets.QMainWindow):
    folderDropped = QtCore.pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e: QtGui.QDragEnterEvent) -> None:
        md = e.mimeData()
        if md and md.hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QtGui.QDropEvent) -> None:
        md = e.mimeData()
        if not md or not md.hasUrls():
            return
        urls = md.urls()
        if not urls:
            return
        p = urls[0].toLocalFile()
        if p and os.path.isdir(p):
            self.folderDropped.emit(p)


class PlayerWindow(DropMainWindow):
    def __init__(self, folder: str, cfg: Dict[str, Any]) -> None:
        super().__init__()

        self.cfg = cfg
        self.folder = _norm(folder)

        self.videos: List[VideoItem] = []
        self.filtered: List[int] = []
        self.current = -1

        self._seeking = False
        self._dur_cache = -1
        self._pending_resume: Optional[int] = None
        self._last_path: Optional[str] = None

        self._shuffle = bool(self.cfg.get("shuffle", False))
        loop = self.cfg.get("loop", "off")
        self._loop = loop if loop in ("off", "one", "all") else "off"

        self._speed = float(self.cfg.get("speed", 1.0) or 1.0)
        self._speed = max(0.25, min(3.0, self._speed))

        self._muted = bool(self.cfg.get("muted", False))
        self._compact = bool(self.cfg.get("compact_sidebar", False))

        if vlc is None:
            QtWidgets.QMessageBox.critical(
                self,
                "Missing dependency",
                "python-vlc is not installed.\nInstall: pip install python-vlc\nAlso install VLC desktop.",
            )
            raise SystemExit(1)

        try:
            args = [
                "--no-video-title-show",
                "--quiet",
                "--no-media-library",
                "--no-one-instance",
                "--no-snapshot-preview",
                "--file-caching=600",
                "--network-caching=800",
                "--avcodec-hw=any",
            ]
            self.vlc_instance = vlc.Instance(args)
            self.player = self.vlc_instance.media_player_new()

            em = self.player.event_manager()
            em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_ended)
            em.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_error)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "VLC init failed",
                "Could not initialize VLC.\nMake sure VLC Desktop is installed.\n\nDetails:\n"
                + str(e),
            )
            raise SystemExit(1)

        self.setWindowTitle(APP_NAME)
        self.resize(1360, 780)

        self._build_ui()
        self._apply_dark()
        self._bind_vlc()
        self._wire()

        self.folderDropped.connect(lambda p: self.rescan(p, autoplay=False))

        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._update_ui)
        self._tick.start()

        self._resume_timer = QtCore.QTimer(self)
        self._resume_timer.setInterval(1200)
        self._resume_timer.timeout.connect(self._save_resume)
        self._resume_timer.start()

        self.rescan(self.folder, autoplay=False)

    def _build_ui(self) -> None:
        self._act_open = QtWidgets.QAction("Open Folder", self)
        self._act_open.setShortcut("Ctrl+O")

        self._act_rescan = QtWidgets.QAction("Rescan", self)
        self._act_rescan.setShortcut("Ctrl+R")

        self._act_full = QtWidgets.QAction("Fullscreen", self)
        self._act_full.setShortcut("F")

        self._act_quit = QtWidgets.QAction("Quit", self)
        self._act_quit.setShortcut("Ctrl+Q")

        self._act_toggle_sidebar = QtWidgets.QAction("Toggle Sidebar", self)
        self._act_toggle_sidebar.setShortcut("Ctrl+B")

        mb = self.menuBar()
        mfile = mb.addMenu("File")
        mfile.addAction(self._act_open)
        mfile.addAction(self._act_rescan)
        mfile.addSeparator()
        mfile.addAction(self._act_quit)

        mview = mb.addMenu("View")
        mview.addAction(self._act_full)
        mview.addAction(self._act_toggle_sidebar)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        root.addWidget(self.split, 1)

        self.left = QtWidgets.QWidget()
        l = QtWidgets.QVBoxLayout(self.left)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(10)

        head = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(head)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        self.lbl_folder = QtWidgets.QLabel("")
        self.lbl_folder.setWordWrap(True)
        self.lbl_folder.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        self.btn_open = QtWidgets.QPushButton("Open")
        self.btn_open.setFixedWidth(90)

        h.addWidget(self.lbl_folder, 1)
        h.addWidget(self.btn_open)
        l.addWidget(head)

        top = QtWidgets.QWidget()
        t = QtWidgets.QHBoxLayout(top)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(10)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search name or folder")

        self.sort = QtWidgets.QComboBox()
        self.sort.addItems(
            [
                "Folder then Name",
                "Name A-Z",
                "Name Z-A",
                "Size Large-Small",
                "Size Small-Large",
            ]
        )

        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_clear.setFixedWidth(90)

        t.addWidget(self.search, 1)
        t.addWidget(self.sort)
        t.addWidget(self.btn_clear)
        l.addWidget(top)

        self.listw = QtWidgets.QListWidget()
        self.listw.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.listw.setUniformItemSizes(True)
        self.listw.setAlternatingRowColors(False)
        l.addWidget(self.listw, 1)

        foot = QtWidgets.QWidget()
        f = QtWidgets.QHBoxLayout(foot)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(10)

        self.lbl_count = QtWidgets.QLabel("0")
        self.lbl_meta = QtWidgets.QLabel("")
        self.lbl_meta.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        f.addWidget(self.lbl_count)
        f.addStretch(1)
        f.addWidget(self.lbl_meta)
        l.addWidget(foot)

        self.right = QtWidgets.QWidget()
        r = QtWidgets.QVBoxLayout(self.right)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(10)

        self.video = VideoSurface()
        self.video.setMinimumHeight(360)
        r.addWidget(self.video, 1)

        row_a = QtWidgets.QWidget()
        a = QtWidgets.QHBoxLayout(row_a)
        a.setContentsMargins(0, 0, 0, 0)
        a.setSpacing(10)

        self.btn_prev = QtWidgets.QPushButton("Previous")
        self.btn_play = QtWidgets.QPushButton("Play")
        self.btn_next = QtWidgets.QPushButton("Next")

        self.btn_shuffle = QtWidgets.QPushButton("Shuffle")
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setChecked(self._shuffle)

        self.btn_loop = QtWidgets.QPushButton("Loop: off")

        self.btn_mute = QtWidgets.QPushButton("Mute")
        self.btn_mute.setCheckable(True)
        self.btn_mute.setChecked(self._muted)

        self.btn_full = QtWidgets.QPushButton("Fullscreen")
        self.btn_full.setCheckable(True)

        a.addWidget(self.btn_prev)
        a.addWidget(self.btn_play)
        a.addWidget(self.btn_next)
        a.addStretch(1)
        a.addWidget(self.btn_shuffle)
        a.addWidget(self.btn_loop)
        a.addWidget(self.btn_mute)
        a.addWidget(self.btn_full)
        r.addWidget(row_a)

        row_b = QtWidgets.QWidget()
        b = QtWidgets.QHBoxLayout(row_b)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(10)

        self.lbl_time = QtWidgets.QLabel("00:00 / 00:00")
        self.lbl_time.setMinimumWidth(140)

        self.seek = ClickableSlider(QtCore.Qt.Horizontal)
        self.seek.setRange(0, 1000)

        b.addWidget(self.lbl_time)
        b.addWidget(self.seek, 1)
        r.addWidget(row_b)

        row_c = QtWidgets.QWidget()
        c2 = QtWidgets.QHBoxLayout(row_c)
        c2.setContentsMargins(0, 0, 0, 0)
        c2.setSpacing(10)

        self.lbl_speed = QtWidgets.QLabel(f"{self._speed:.2f}x")
        self.lbl_speed.setMinimumWidth(56)

        self.sld_speed = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_speed.setRange(25, 300)
        self.sld_speed.setValue(int(self._speed * 100))
        self.sld_speed.setFixedWidth(220)

        self.lbl_vol = QtWidgets.QLabel("Volume")
        self.lbl_vol.setMinimumWidth(60)

        self.sld_vol = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_vol.setRange(0, 100)
        self.sld_vol.setValue(int(self.cfg.get("volume", 80)))
        self.sld_vol.setFixedWidth(220)

        self.btn_sub = QtWidgets.QPushButton("Subtitles")
        self.btn_audio = QtWidgets.QPushButton("Audio")
        self.btn_info = QtWidgets.QPushButton("Info")

        c2.addWidget(self.lbl_speed)
        c2.addWidget(self.sld_speed)
        c2.addSpacing(8)
        c2.addWidget(self.lbl_vol)
        c2.addWidget(self.sld_vol)
        c2.addStretch(1)
        c2.addWidget(self.btn_audio)
        c2.addWidget(self.btn_sub)
        c2.addWidget(self.btn_info)

        r.addWidget(row_c)

        self.split.addWidget(self.left)
        self.split.addWidget(self.right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)

        if self._compact:
            self.left.setMaximumWidth(360)

        self._update_loop_btn()
        self._apply_muted()
        self.lbl_folder.setText(self.folder)

    def _apply_dark(self) -> None:
        qss = """
        QWidget{background:#0b0f14;color:#d7dde6;font-family:Segoe UI,Inter,Arial;font-size:12px;}
        QMenuBar{background:#0b0f14;border-bottom:1px solid #1c2a3c;}
        QMenuBar::item{padding:6px 10px;border-radius:8px;background:transparent;}
        QMenuBar::item:selected{background:#132033;}
        QMenu{background:#0f1520;border:1px solid #24364d;border-radius:12px;padding:6px;}
        QMenu::item{padding:8px 10px;border-radius:10px;}
        QMenu::item:selected{background:#1a2a46;}
        QLineEdit,QComboBox,QListWidget{background:#0f1520;border:1px solid #223044;border-radius:12px;padding:10px;}
        QComboBox::drop-down{border:0;width:22px;}
        QPushButton{background:#142033;border:1px solid #24364d;border-radius:12px;padding:10px 12px;}
        QPushButton:hover{background:#182742;}
        QPushButton:pressed{background:#0f1a2b;}
        QPushButton:checked{background:#1c2f52;border:1px solid #2c4772;}
        QLabel{background:transparent;}
        QSlider::groove:horizontal{height:7px;background:#1a2436;border-radius:4px;}
        QSlider::handle:horizontal{width:16px;margin:-7px 0;border-radius:8px;background:#d7dde6;}
        QListWidget::item{padding:10px;border-radius:12px;}
        QListWidget::item:selected{background:#1a2a46;}
        QListWidget::item:hover{background:#131d2f;}
        QSplitter::handle{background:#0b0f14;}
        """
        self.setStyleSheet(qss)
        self.video.setStyleSheet("background:#000;border:1px solid #24364d;border-radius:16px;")

    def _bind_vlc(self) -> None:
        wid = int(self.video.winId())
        sysn = platform.system().lower()
        try:
            if "windows" in sysn:
                self.player.set_hwnd(wid)
            elif "darwin" in sysn:
                self.player.set_nsobject(wid)
            else:
                self.player.set_xwindow(wid)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Bind failed", f"Failed to bind VLC output.\n\n{e}")

    def _wire(self) -> None:
        self._act_open.triggered.connect(self._open_folder)
        self._act_rescan.triggered.connect(lambda: self.rescan(self.folder, autoplay=False))
        self._act_quit.triggered.connect(self.close)
        self._act_full.triggered.connect(lambda: self.btn_full.toggle())
        self._act_toggle_sidebar.triggered.connect(self._toggle_sidebar)

        self.btn_open.clicked.connect(self._open_folder)
        self.btn_clear.clicked.connect(lambda: self.search.setText(""))

        self.search.textChanged.connect(self._rebuild_keep)
        self.sort.currentIndexChanged.connect(self._rebuild_keep)

        self.listw.itemClicked.connect(self._select_row)
        self.listw.itemDoubleClicked.connect(lambda _: self.play_selected())

        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_next.clicked.connect(self.next_video)
        self.btn_prev.clicked.connect(self.prev_video)

        self.btn_shuffle.toggled.connect(self._set_shuffle)
        self.btn_loop.clicked.connect(self._cycle_loop)
        self.btn_mute.toggled.connect(self._set_muted)
        self.btn_full.toggled.connect(self._toggle_full)

        self.video.doubleClicked.connect(lambda: self.btn_full.toggle())

        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(self._seek_moved)

        self.sld_vol.valueChanged.connect(self._set_volume)
        self.sld_speed.valueChanged.connect(self._set_speed_slider)

        self.btn_audio.clicked.connect(self._audio_menu)
        self.btn_sub.clicked.connect(self._sub_menu)
        self.btn_info.clicked.connect(self._show_info)

        QtWidgets.QShortcut(QtGui.QKeySequence("Space"), self, activated=self.toggle_play)
        QtWidgets.QShortcut(QtGui.QKeySequence("Right"), self, activated=lambda: self._skip(5000))
        QtWidgets.QShortcut(QtGui.QKeySequence("Left"), self, activated=lambda: self._skip(-5000))
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Right"), self, activated=lambda: self._skip(15000))
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Left"), self, activated=lambda: self._skip(-15000))
        QtWidgets.QShortcut(QtGui.QKeySequence("N"), self, activated=self.next_video)
        QtWidgets.QShortcut(QtGui.QKeySequence("P"), self, activated=self.prev_video)
        QtWidgets.QShortcut(QtGui.QKeySequence("M"), self, activated=lambda: self.btn_mute.toggle())
        QtWidgets.QShortcut(QtGui.QKeySequence("S"), self, activated=lambda: self.btn_shuffle.toggle())
        QtWidgets.QShortcut(QtGui.QKeySequence("R"), self, activated=self._cycle_loop)
        QtWidgets.QShortcut(QtGui.QKeySequence("Esc"), self, activated=self._escape_full)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+L"), self, activated=self._focus_search)
        QtWidgets.QShortcut(QtGui.QKeySequence("["), self, activated=lambda: self._bump_speed(-0.1))
        QtWidgets.QShortcut(QtGui.QKeySequence("]"), self, activated=lambda: self._bump_speed(0.1))

    def _toggle_sidebar(self) -> None:
        self._compact = not self._compact
        self.cfg["compact_sidebar"] = self._compact
        _save_cfg(self.cfg)
        if self._compact:
            self.left.setMaximumWidth(360)
        else:
            self.left.setMaximumWidth(16777215)

    def _open_folder(self) -> None:
        folder = _pick_folder(self, last=self.folder)
        if folder:
            self.rescan(folder, autoplay=False)

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _escape_full(self) -> None:
        if self.isFullScreen():
            self.btn_full.setChecked(False)

    def _toggle_full(self, on: bool) -> None:
        if on:
            self.showFullScreen()
        else:
            self.showNormal()

    def _set_shuffle(self, on: bool) -> None:
        self._shuffle = bool(on)
        self.cfg["shuffle"] = self._shuffle
        _save_cfg(self.cfg)

    def _cycle_loop(self) -> None:
        self._loop = "one" if self._loop == "off" else ("all" if self._loop == "one" else "off")
        self.cfg["loop"] = self._loop
        _save_cfg(self.cfg)
        self._update_loop_btn()

    def _update_loop_btn(self) -> None:
        self.btn_loop.setText(f"Loop: {self._loop}")

    def _set_muted(self, on: bool) -> None:
        self._muted = bool(on)
        self.cfg["muted"] = self._muted
        _save_cfg(self.cfg)
        self._apply_muted()

    def _apply_muted(self) -> None:
        try:
            self.player.audio_set_mute(self._muted)
        except Exception:
            pass
        self.btn_mute.setText("Muted" if self._muted else "Mute")

    def _set_volume(self, v: int) -> None:
        try:
            self.player.audio_set_volume(int(v))
        except Exception:
            pass
        self.cfg["volume"] = int(v)
        _save_cfg(self.cfg)

    def _set_speed_slider(self, val: int) -> None:
        sp = max(0.25, min(3.0, val / 100.0))
        self._speed = sp
        self.lbl_speed.setText(f"{sp:.2f}x")
        try:
            self.player.set_rate(float(sp))
        except Exception:
            pass
        self.cfg["speed"] = float(sp)
        _save_cfg(self.cfg)

    def _bump_speed(self, delta: float) -> None:
        sp = max(0.25, min(3.0, self._speed + delta))
        self.sld_speed.setValue(int(sp * 100))

    def rescan(self, folder: str, autoplay: bool = False) -> None:
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(self, "Invalid folder", "That folder is not valid.")
            return

        self.folder = _norm(folder)
        self.lbl_folder.setText(self.folder)
        self.cfg["last_folder"] = self.folder
        _save_cfg(self.cfg)

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.videos = _scan(self.folder)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.current = -1
        self._rebuild(False)

        if not self.videos:
            QtWidgets.QMessageBox.information(
                self,
                "No videos found",
                "No supported video files were found in that folder (including subfolders).",
            )
            return

        self.listw.setCurrentRow(0)
        self._select_row()
        if autoplay:
            self.play_selected()

    def _sorted_indices(self) -> List[int]:
        idxs = list(range(len(self.videos)))
        mode = self.sort.currentText()

        if mode == "Name A-Z":
            idxs.sort(key=lambda i: self.videos[i].name.lower())
        elif mode == "Name Z-A":
            idxs.sort(key=lambda i: self.videos[i].name.lower(), reverse=True)
        elif mode == "Size Large-Small":
            idxs.sort(key=lambda i: self.videos[i].size, reverse=True)
        elif mode == "Size Small-Large":
            idxs.sort(key=lambda i: self.videos[i].size)
        else:
            idxs.sort(key=lambda i: (self.videos[i].folder.lower(), self.videos[i].name.lower()))
        return idxs

    def _rebuild_keep(self) -> None:
        self._rebuild(True)

    def _rebuild(self, keep: bool) -> None:
        sel = self._cur_path() if keep else None
        q = self.search.text().strip().lower()

        idxs = self._sorted_indices()
        self.filtered = []
        self.listw.clear()

        for i in idxs:
            v = self.videos[i]
            blob = (v.name + " " + v.rel).lower()
            if q and q not in blob:
                continue

            self.filtered.append(i)

            title = v.rel.replace("\\", "/")
            meta = _fmt_bytes(v.size)

            it = QtWidgets.QListWidgetItem(title)
            it.setToolTip(f"{v.path}\n{meta}")
            it.setData(QtCore.Qt.UserRole, i)
            it.setData(QtCore.Qt.UserRole + 1, v.path)
            self.listw.addItem(it)

        self.lbl_count.setText(f"{len(self.filtered)} videos")

        if not self.filtered:
            self.listw.addItem("(No matches)")
            self.listw.setEnabled(False)
            self.current = -1
            self.lbl_meta.setText("")
            return

        self.listw.setEnabled(True)

        if sel:
            for row, i in enumerate(self.filtered):
                if self.videos[i].path == sel:
                    self.listw.setCurrentRow(row)
                    self._select_row()
                    return

        self.listw.setCurrentRow(0)
        self._select_row()

    def _select_row(self, *_: object) -> None:
        if not self.filtered:
            self.current = -1
            self.lbl_meta.setText("")
            return

        row = self.listw.currentRow()
        if row < 0 or row >= len(self.filtered):
            row = 0

        self.current = self.filtered[row]
        v = self.videos[self.current]
        rel = v.rel.replace("\\", "/")
        self.lbl_meta.setText(f"{rel}   {_fmt_bytes(v.size)}")

    def _cur_path(self) -> Optional[str]:
        if self.current is None or self.current < 0 or self.current >= len(self.videos):
            return None
        return self.videos[self.current].path

    def play_selected(self) -> None:
        if not self.filtered:
            return
        self._select_row()
        if self.current < 0:
            return
        self.play_index(self.current)

    def play_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.videos):
            return

        path = self.videos[idx].path
        if not os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, "Missing file", f"File not found:\n{path}")
            return

        self.current = idx
        self._sync_selection()
        self._dur_cache = -1
        self._pending_resume = None

        try:
            media = self.vlc_instance.media_new_path(path)
            self.player.set_media(media)
            self.player.play()
            try:
                self.player.set_rate(float(self._speed))
            except Exception:
                pass
            self.btn_play.setText("Pause")
            self._last_path = path
            self._queue_resume(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Playback error",
                f"Could not play:\n{path}\n\nDetails:\n{e}",
            )

    def _sync_selection(self) -> None:
        if not self.filtered:
            return
        try:
            for row, i in enumerate(self.filtered):
                if i == self.current:
                    self.listw.blockSignals(True)
                    self.listw.setCurrentRow(row)
                    self.listw.blockSignals(False)
                    self._select_row()
                    break
        except Exception:
            pass

    def toggle_play(self) -> None:
        if not self.videos:
            return

        st = self.player.get_state() if vlc else None
        if st in (vlc.State.Ended, vlc.State.Stopped, vlc.State.NothingSpecial) and self.current >= 0:
            self.play_index(self.current)
            return

        if self.player.is_playing():
            self.player.pause()
            self.btn_play.setText("Play")
            return

        if self.player.get_media() is None:
            if self.current < 0 and self.filtered:
                r = self.listw.currentRow()
                r = 0 if r < 0 else r
                self.current = self.filtered[r]
            if self.current < 0 and self.videos:
                self.current = 0
            if self.current >= 0:
                self.play_index(self.current)
            return

        self.player.play()
        self.btn_play.setText("Pause")

    def _pick_next(self) -> Optional[int]:
        if not self.videos:
            return None
        if self._loop == "one":
            return self.current
        if self._shuffle:
            pool = list(range(len(self.videos)))
            if len(pool) > 1 and self.current in pool:
                pool.remove(self.current)
            return random.choice(pool) if pool else self.current

        nxt = self.current + 1
        if nxt >= len(self.videos):
            return 0 if self._loop == "all" else self.current
        return nxt

    def _pick_prev(self) -> Optional[int]:
        if not self.videos:
            return None
        if self._loop == "one":
            return self.current
        if self._shuffle:
            pool = list(range(len(self.videos)))
            if len(pool) > 1 and self.current in pool:
                pool.remove(self.current)
            return random.choice(pool) if pool else self.current

        prv = self.current - 1
        if prv < 0:
            return (len(self.videos) - 1) if self._loop == "all" else self.current
        return prv

    def next_video(self) -> None:
        if not self.videos:
            return
        if self.current < 0:
            self.current = 0
        nxt = self._pick_next()
        if nxt is None:
            return
        self.play_index(nxt)

    def prev_video(self) -> None:
        if not self.videos:
            return
        if self.current < 0:
            self.current = 0
        prv = self._pick_prev()
        if prv is None:
            return
        self.play_index(prv)

    def _seek_pressed(self) -> None:
        self._seeking = True

    def _seek_moved(self, val: int) -> None:
        dur = self._dur()
        if dur > 0:
            t = int((val / 1000.0) * dur)
            self.lbl_time.setText(f"{_fmt_ms(t)} / {_fmt_ms(dur)}")

    def _seek_released(self) -> None:
        if not self._seeking:
            return
        self._seeking = False

        dur = self._dur()
        if dur <= 0:
            return

        val = self.seek.value()
        t = int((val / 1000.0) * dur)
        try:
            self.player.set_time(t)
        except Exception:
            pass

    def _dur(self) -> int:
        dur = -1
        try:
            dur = int(self.player.get_length())
        except Exception:
            dur = -1
        if dur > 0:
            self._dur_cache = dur
        return self._dur_cache

    def _skip(self, delta: int) -> None:
        dur = self._dur()
        try:
            cur = int(self.player.get_time())
        except Exception:
            return
        if dur <= 0 or cur < 0:
            return

        t = max(0, min(dur, cur + delta))
        try:
            self.player.set_time(t)
        except Exception:
            pass

    def _update_ui(self) -> None:
        if self._seeking:
            return

        dur = self._dur()
        cur = -1
        try:
            cur = int(self.player.get_time())
        except Exception:
            cur = -1

        if dur > 0 and cur >= 0:
            pos = int((cur / dur) * 1000)
            pos = max(0, min(1000, pos))
            self.seek.blockSignals(True)
            self.seek.setValue(pos)
            self.seek.blockSignals(False)
            self.lbl_time.setText(f"{_fmt_ms(cur)} / {_fmt_ms(dur)}")
        else:
            self.btn_play.setText("Pause" if self.player.is_playing() else "Play")

        if self._pending_resume is not None and dur > 0:
            t = min(max(0, int(self._pending_resume)), max(0, dur - 1500))
            try:
                self.player.set_time(t)
                self._pending_resume = None
            except Exception:
                pass

    def _on_ended(self, _event: object) -> None:
        QtCore.QMetaObject.invokeMethod(self, "_handle_ended", QtCore.Qt.QueuedConnection)

    @QtCore.pyqtSlot()
    def _handle_ended(self) -> None:
        if not self.videos:
            return
        if self._loop == "one":
            self.play_index(self.current)
            return
        if self._loop == "off" and self.current == len(self.videos) - 1 and not self._shuffle:
            self.btn_play.setText("Play")
            return
        self.next_video()

    def _on_error(self, _event: object) -> None:
        QtCore.QMetaObject.invokeMethod(self, "_handle_error", QtCore.Qt.QueuedConnection)

    @QtCore.pyqtSlot()
    def _handle_error(self) -> None:
        self.btn_play.setText("Play")
        p = self._cur_path()
        if p:
            QtWidgets.QMessageBox.warning(self, "Playback error", f"VLC reported an error while playing:\n{p}")

    def _queue_resume(self, path: str) -> None:
        res = self.cfg.get("resume", {})
        try:
            ms = int(res.get(path, -1))
        except Exception:
            ms = -1
        if ms > 2000:
            self._pending_resume = ms

    def _save_resume(self) -> None:
        if not self.videos:
            return
        p = self._cur_path()
        if not p:
            return
        if self.player.get_media() is None:
            return

        try:
            cur = int(self.player.get_time())
            dur = int(self.player.get_length())
        except Exception:
            return

        if dur <= 0 or cur < 0:
            return
        if cur < 2000:
            return

        res = self.cfg.get("resume", {})
        if not isinstance(res, dict):
            res = {}

        if cur > dur - 2000:
            if p in res:
                res.pop(p, None)
        else:
            res[p] = cur

        self.cfg["resume"] = res
        _save_cfg(self.cfg)

    def _audio_menu(self) -> None:
        m = QtWidgets.QMenu(self)
        try:
            tracks = self.player.audio_get_track_description() or []
        except Exception:
            tracks = []

        if not tracks:
            a = m.addAction("No audio tracks")
            a.setEnabled(False)
        else:
            try:
                current = int(self.player.audio_get_track())
            except Exception:
                current = -1

            for tid, name in tracks:
                act = m.addAction(str(name))
                act.setCheckable(True)
                act.setChecked(int(tid) == current)
                act.triggered.connect(lambda _checked=False, tid=int(tid): self._set_audio_track(tid))

        m.exec_(QtGui.QCursor.pos())

    def _set_audio_track(self, tid: int) -> None:
        try:
            self.player.audio_set_track(int(tid))
        except Exception:
            pass

    def _sub_menu(self) -> None:
        m = QtWidgets.QMenu(self)
        try:
            tracks = self.player.video_get_spu_description() or []
        except Exception:
            tracks = []

        if not tracks:
            a = m.addAction("No subtitle tracks")
            a.setEnabled(False)
        else:
            try:
                current = int(self.player.video_get_spu())
            except Exception:
                current = -1

            for tid, name in tracks:
                act = m.addAction(str(name))
                act.setCheckable(True)
                act.setChecked(int(tid) == current)
                act.triggered.connect(lambda _checked=False, tid=int(tid): self._set_sub_track(tid))

        m.addSeparator()
        add = m.addAction("Load subtitle file")
        add.triggered.connect(self._load_sub_file)
        m.exec_(QtGui.QCursor.pos())

    def _set_sub_track(self, tid: int) -> None:
        try:
            self.player.video_set_spu(int(tid))
        except Exception:
            pass

    def _load_sub_file(self) -> None:
        dlg = QtWidgets.QFileDialog(self, "Load subtitle file")
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dlg.setNameFilters(
            [
                "Subtitle files (*.srt *.ass *.ssa *.vtt *.sub *.idx)",
                "All files (*)",
            ]
        )

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        files = dlg.selectedFiles()
        if not files:
            return

        p = files[0]
        try:
            self.player.add_slave(vlc.MediaSlaveType.subtitle, p, True)
            return
        except Exception:
            pass

        try:
            md = self.player.get_media()
            if md:
                md.add_slave(vlc.MediaSlaveType.subtitle, p, True)
                return
        except Exception:
            pass

        QtWidgets.QMessageBox.warning(self, "Subtitles", "Could not load subtitles.")

    def _show_info(self) -> None:
        p = self._cur_path()
        if not p:
            QtWidgets.QMessageBox.information(self, "Info", "No file selected.")
            return

        v = self.videos[self.current]
        dur = self._dur()

        lines: List[str] = []
        lines.append(f"File: {v.path}")
        lines.append(f"Size: {_fmt_bytes(v.size)}")
        if dur > 0:
            lines.append(f"Duration: {_fmt_ms(dur)}")

        try:
            w, h = self.player.video_get_size(0)
            if w and h:
                lines.append(f"Video: {w}x{h}")
        except Exception:
            pass

        try:
            sp = self.player.get_rate()
            if sp:
                lines.append(f"Speed: {sp:.2f}x")
        except Exception:
            pass

        QtWidgets.QMessageBox.information(self, "Info", "\n".join(lines))

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        try:
            self._save_resume()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        e.accept()


def _pick_folder(parent: Optional[QtWidgets.QWidget] = None, last: Optional[str] = None) -> Optional[str]:
    dlg = QtWidgets.QFileDialog(parent, "Select a folder with videos")
    dlg.setFileMode(QtWidgets.QFileDialog.Directory)
    dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
    dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
    dlg.setOption(QtWidgets.QFileDialog.DontResolveSymlinks, True)
    dlg.setViewMode(QtWidgets.QFileDialog.Detail)

    if last and os.path.isdir(last):
        try:
            dlg.setDirectory(last)
        except Exception:
            pass

    if dlg.exec_() == QtWidgets.QDialog.Accepted:
        s = dlg.selectedFiles()
        if s:
            return s[0]
    return None


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)

    cfg = _load_cfg()
    last = cfg.get("last_folder")

    folder = _pick_folder(None, last=last)
    if not folder:
        QtWidgets.QMessageBox.information(None, "No folder selected", "No folder was selected. Exiting.")
        return

    if not os.path.isdir(folder):
        QtWidgets.QMessageBox.critical(None, "Invalid folder", "The selected path is not a folder. Exiting.")
        return

    cfg["last_folder"] = _norm(folder)
    _save_cfg(cfg)

    win = PlayerWindow(_norm(folder), cfg)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()