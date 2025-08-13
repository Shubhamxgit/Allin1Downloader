#!/usr/bin/env python3
# multi_downloader_polished.py
"""
Multi Social Media Downloader — Polished single-file app.

Features:
- Single exe-friendly file (tray + GUI)
- Default startup OFF; can toggle from settings (Windows Run key)
- Clipboard detection (optional)
- Content-type detection: video/audio -> yt-dlp, image/gallery -> gallery-dl fallback
- Best quality direct download OR format picker based on yt-dlp extract_info
- Cookie support for logged-in sites (cookies.txt)
- Download folder chooser (default: C:\Downloads)
- Dark theme toggle (persisted)
- Smooth animated progress bars (item + batch)
- Batch CSV support (paste lines or load file)
- Lazy imports and threaded downloads to keep UI responsive and low-resource when idle
"""

import sys
import os
import json
import time
import math
import traceback
import subprocess
from pathlib import Path
from io import BytesIO
from datetime import timedelta
from urllib.parse import unquote, urlparse, parse_qs

import requests
from PIL import Image

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QTextEdit,
    QVBoxLayout, QHBoxLayout, QFileDialog, QProgressBar, QMessageBox,
    QCheckBox, QComboBox, QSpinBox, QSystemTrayIcon, QMenu, QAction, QStyle
)

# Optional Windows registry import (used for startup toggle)
try:
    import winreg
except Exception:
    winreg = None

# ---------------- Config ----------------
CONFIG_FILE = Path.home() / ".multi_downloader_config.json"
DEFAULT_DOWNLOAD_DIR = Path("C:/Downloads")
DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be", "facebook.com", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "reddit.com", "pinterest.com", "twitch.tv",
    "soundcloud.com", "vimeo.com", "bilibili.com", "mixcloud.com", "rumble.com",
    "odnoklassniki.ru", "ted.com"
]

def load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

# -------------- Utilities --------------
def normalize_url(url: str) -> str:
    if not url:
        return url
    u = url.strip()
    if "reddit.com/media" in u and "url=" in u:
        try:
            qs = parse_qs(urlparse(u).query)
            if "url" in qs and qs["url"]:
                return unquote(qs["url"][0])
        except Exception:
            pass
    return u

def friendly_size(n):
    try:
        if not n:
            return "N/A"
        n = float(n)
        for unit in ["B","KB","MB","GB","TB"]:
            if n < 1024:
                return f"{n:3.1f}{unit}"
            n /= 1024.0
        return f"{n:.1f}PB"
    except Exception:
        return "N/A"

def seconds_to_hhmmss(sec):
    try:
        return str(timedelta(seconds=int(sec)))
    except Exception:
        return "00:00:00"

def thumbnail_pixmap_from_url(url, max_w=320):
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        im = Image.open(BytesIO(r.content))
        im.thumbnail((max_w, max_w*2))
        buf = BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        pix = QPixmap()
        pix.loadFromData(buf.read())
        return pix
    except Exception:
        return None

# -------------- Workers --------------
class YTDLPWorker(QThread):
    progress = pyqtSignal(float, str)  # percent, speed/extra
    finished = pyqtSignal(dict)        # {"ok":bool, "url":..., "error":...}
    status = pyqtSignal(str)

    def __init__(self, url, outdir, format_id=None, cookies=None, proxy=None, sections=None, retries=3, use_best=True):
        super().__init__()
        self.url = url
        self.outdir = str(outdir)
        self.format_id = format_id
        self.cookies = cookies
        self.proxy = proxy
        self.sections = sections
        self.retries = retries
        self.use_best = use_best

    def run(self):
        # lazy import
        try:
            import yt_dlp
        except Exception as e:
            self.finished.emit({"ok": False, "error": f"yt-dlp import error: {e}"})
            return

        fmt = None if self.use_best else self.format_id
        outtmpl = os.path.join(self.outdir, "%(title)s.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "continuedl": True,
            "retries": 2,
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "progress_hooks": [self._progress_hook],
            "format": fmt or "bestvideo+bestaudio/best",
            "concurrent_fragment_downloads": 3
        }
        if self.cookies:
            ydl_opts["cookiefile"] = self.cookies
        if self.proxy:
            ydl_opts["proxy"] = self.proxy
        if self.sections:
            ydl_opts["download_sections"] = {"*": self.sections}

        last_err = None
        for attempt in range(1, self.retries+1):
            try:
                self.status.emit(f"Starting download (attempt {attempt})")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self.url])
                self.finished.emit({"ok": True, "url": self.url})
                return
            except Exception as e:
                last_err = e
                self.status.emit(f"Error: {e} (retrying {attempt}/{self.retries})")
                # exponential backoff
                time.sleep(min(10, 1.5 ** attempt))
        self.finished.emit({"ok": False, "url": self.url, "error": str(last_err)})

    def _progress_hook(self, d):
        try:
            if d.get("status") == "downloading":
                pct = 0.0
                if d.get("_percent_str"):
                    try:
                        pct = float(d["_percent_str"].replace("%", "").strip())
                    except:
                        pct = 0.0
                speed = d.get("_speed_str", "")
                self.progress.emit(pct, speed)
            elif d.get("status") == "finished":
                self.progress.emit(100.0, "processing")
        except Exception:
            pass

class GalleryDLWorker(QThread):
    finished = pyqtSignal(dict)  # {"ok":bool, "out":...}
    status = pyqtSignal(str)

    def __init__(self, url, outdir, cookies=None, timeout=90):
        super().__init__()
        self.url = url
        self.outdir = str(outdir)
        self.cookies = cookies
        self.timeout = timeout

    def run(self):
        try:
            cmd = ["gallery-dl", "-d", self.outdir, self.url]
            if self.cookies:
                cmd.extend(["--cookies", self.cookies])
            self.status.emit("Running gallery-dl...")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            if proc.returncode == 0:
                self.finished.emit({"ok": True, "out": proc.stdout.strip() or "gallery-dl succeeded"})
            else:
                msg = (proc.stderr or proc.stdout or f"gallery-dl exit {proc.returncode}").strip()
                self.finished.emit({"ok": False, "out": msg})
        except FileNotFoundError:
            self.finished.emit({"ok": False, "out": "gallery-dl not found (install it)."})
        except subprocess.TimeoutExpired:
            self.finished.emit({"ok": False, "out": "gallery-dl timeout."})
        except Exception as e:
            self.finished.emit({"ok": False, "out": f"gallery-dl error: {e}"})

# -------------- Main App --------------
class MultiDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.download_dir = Path(self.cfg.get("download_dir", str(DEFAULT_DOWNLOAD_DIR)))
        self.cookies = self.cfg.get("cookies", "")
        self.proxy = self.cfg.get("proxy", "")
        self.dark_mode = self.cfg.get("dark_mode", False)
        self.clip_enabled = False
        self.clip_last = ""
        self.startup_enabled = self.cfg.get("startup", False)

        self.current_worker = None
        self.gallery_worker = None
        self.queue = []  # list of urls for batch
        self.batch_total = 0
        self.batch_done = 0

        self._build_ui()
        self._connect_signals()
        self._setup_tray()
        if self.dark_mode:
            self.apply_dark_theme(True)

        # smooth progress interpolation
        self.item_target_pct = 0.0
        self.item_display_pct = 0.0
        self.item_progress_timer = QTimer(self)
        self.item_progress_timer.setInterval(40)  # ~25fps
        self.item_progress_timer.timeout.connect(self._animate_item_progress)
        self.item_progress_timer.start()

        # clipboard timer (lightweight, default off)
        self.clip_timer = QTimer(self)
        self.clip_timer.setInterval(2000)
        self.clip_timer.timeout.connect(self._check_clipboard)

    # ---------- UI build ----------
    def _build_ui(self):
        self.setWindowTitle("Multi Social Media Downloader")
        self.resize(980, 640)
        main = QVBoxLayout(self)

        top_row = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("Paste one or multiple URLs (one per line):"))
        self.urls_text = QTextEdit()
        self.urls_text.setPlaceholderText("https://... (one per line)")
        left_col.addWidget(self.urls_text)

        btn_row = QHBoxLayout()
        self.fetch_btn = QPushButton("Fetch Info")
        self.direct_btn = QPushButton("Direct Download (Best)")
        self.choose_btn = QPushButton("Fetch & Choose Format")
        self.load_csv_btn = QPushButton("Load CSV")
        btn_row.addWidget(self.fetch_btn)
        btn_row.addWidget(self.direct_btn)
        btn_row.addWidget(self.choose_btn)
        btn_row.addWidget(self.load_csv_btn)
        left_col.addLayout(btn_row)

        cookies_row = QHBoxLayout()
        cookies_row.addWidget(QLabel("Cookies (optional):"))
        self.cookies_edit = QLineEdit(self.cookies or "")
        cookies_row.addWidget(self.cookies_edit)
        self.browse_cookies = QPushButton("Browse")
        cookies_row.addWidget(self.browse_cookies)
        left_col.addLayout(cookies_row)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Download folder:"))
        self.folder_label = QLabel(str(self.download_dir))
        folder_row.addWidget(self.folder_label)
        self.change_folder_btn = QPushButton("Change...")
        folder_row.addWidget(self.change_folder_btn)
        left_col.addLayout(folder_row)

        top_row.addLayout(left_col, 2)

        right_col = QVBoxLayout()
        self.thumb_label = QLabel("Thumbnail")
        self.thumb_label.setFixedSize(360, 200)
        self.thumb_label.setStyleSheet("border:1px solid #888; background:#111;")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        right_col.addWidget(self.thumb_label)
        self.meta_label = QLabel("Metadata will appear here.")
        self.meta_label.setWordWrap(True)
        right_col.addWidget(self.meta_label)

        fmt_row = QHBoxLayout()
        self.best_checkbox = QCheckBox("Best quality (direct)")
        self.best_checkbox.setChecked(True)
        fmt_row.addWidget(self.best_checkbox)
        fmt_row.addWidget(QLabel("Formats:"))
        self.format_combo = QComboBox()
        self.format_combo.setEnabled(False)
        fmt_row.addWidget(self.format_combo, 1)
        right_col.addLayout(fmt_row)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Start (hh:mm:ss):"))
        self.start_time_edit = QLineEdit("00:00:00")
        time_row.addWidget(self.start_time_edit)
        time_row.addWidget(QLabel("End (hh:mm:ss):"))
        self.end_time_edit = QLineEdit("00:00:00")
        time_row.addWidget(self.end_time_edit)
        right_col.addLayout(time_row)

        # progress bars
        self.item_progress = QProgressBar()
        self.item_progress.setValue(0)
        self.item_progress.setFormat("Item: %p%")
        self.overall_progress = QProgressBar()
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("Overall: %p%")
        right_col.addWidget(self.item_progress)
        right_col.addWidget(self.overall_progress)

        # status/log
        self.status_label = QLabel("Idle")
        right_col.addWidget(self.status_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(140)
        right_col.addWidget(self.log_text)

        # settings row
        settings_row = QHBoxLayout()
        self.dark_toggle = QCheckBox("Dark theme")
        self.dark_toggle.setChecked(self.dark_mode)
        settings_row.addWidget(self.dark_toggle)
        self.clip_toggle = QCheckBox("Clipboard watch (off)")
        self.clip_toggle.setChecked(False)
        settings_row.addWidget(self.clip_toggle)
        self.startup_toggle = QCheckBox("Start with Windows (off)")
        self.startup_toggle.setChecked(bool(self.startup_enabled))
        settings_row.addWidget(self.startup_toggle)
        settings_row.addStretch()
        self.save_settings_btn = QPushButton("Save Settings")
        settings_row.addWidget(self.save_settings_btn)

        right_col.addLayout(settings_row)

        top_row.addLayout(right_col, 1)

        main.addLayout(top_row)

        self.setLayout(main)

    # ---------- Connect signals ----------
    def _connect_signals(self):
        self.fetch_btn.clicked.connect(self.on_fetch_info)
        self.direct_btn.clicked.connect(self.on_direct_download)
        self.choose_btn.clicked.connect(self.on_choose_and_download)
        self.load_csv_btn.clicked.connect(self.on_load_csv)
        self.browse_cookies.clicked.connect(self.on_browse_cookies)
        self.change_folder_btn.clicked.connect(self.on_change_folder)
        self.format_combo.currentIndexChanged.connect(lambda _: self.best_checkbox.setChecked(False))
        self.browse_cookies.clicked.connect(self.on_browse_cookies)
        self.save_settings_btn.clicked.connect(self.on_save_settings)
        self.dark_toggle.stateChanged.connect(self.on_toggle_dark)
        self.clip_toggle.stateChanged.connect(self.on_toggle_clip)
        self.startup_toggle.stateChanged.connect(self.on_toggle_startup)

    # ---------- Tray icon ----------
    def _setup_tray(self):
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        open_action = QAction("Open Downloader")
        open_action.triggered.connect(self.show_window)
        menu.addAction(open_action)

        toggle_clip_action = QAction("Enable Clipboard Watch")
        def _toggle_clip():
            new_state = not self.clip_toggle.isChecked()
            self.clip_toggle.setChecked(new_state)
            toggle_clip_action.setText("Pause Clipboard Watch" if new_state else "Enable Clipboard Watch")
        toggle_clip_action.triggered.connect(_toggle_clip)
        menu.addAction(toggle_clip_action)

        toggle_startup_action = QAction("Enable startup" if not self.startup_enabled else "Disable startup")
        def _toggle_startup():
            new_state = not self.startup_toggle.isChecked()
            self.startup_toggle.setChecked(new_state)
            toggle_startup_action.setText("Enable startup" if not new_state else "Disable startup")
        toggle_startup_action.triggered.connect(_toggle_startup)
        menu.addAction(toggle_startup_action)

        menu.addSeparator()
        exit_action = QAction("Exit")
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def exit_app(self):
        try:
            self.tray.hide()
        except Exception:
            pass
        QApplication.quit()

    # ---------- Settings handlers ----------
    def on_save_settings(self):
        self.cfg["download_dir"] = str(self.download_dir)
        self.cfg["cookies"] = self.cookies_edit.text().strip()
        self.cfg["proxy"] = self.proxy
        self.cfg["dark_mode"] = bool(self.dark_toggle.isChecked())
        self.cfg["startup"] = bool(self.startup_toggle.isChecked())
        save_config(self.cfg)
        QMessageBox.information(self, "Saved", "Settings saved.")

    def on_toggle_dark(self, state):
        on = bool(state == Qt.Checked)
        self.apply_dark_theme(on)
        self.cfg["dark_mode"] = on
        save_config(self.cfg)

    def apply_dark_theme(self, on: bool):
        if on:
            self.setStyleSheet("""
                QWidget { background: #2b2b2b; color: #ddd; }
                QPushButton { background: #444; color: #fff; border: 1px solid #666; padding:6px; border-radius:4px; }
                QLineEdit, QTextEdit, QComboBox { background: #333; color: #fff; border: 1px solid #555; }
                QProgressBar { background: #333; color: #fff; border:1px solid #555; height:16px; }
            """)
        else:
            self.setStyleSheet("")

    def on_toggle_clip(self, state):
        enable = bool(state == Qt.Checked)
        self.clip_enabled = enable
        if enable:
            self.clip_timer.start()
            self.log("Clipboard watch enabled")
        else:
            self.clip_timer.stop()
            self.log("Clipboard watch paused")

    def on_toggle_startup(self, state):
        enable = bool(state == Qt.Checked)
        ok, msg = self._set_startup(enable)
        if not ok:
            QMessageBox.warning(self, "Startup", f"Could not change startup setting: {msg}")
            # revert toggle visually
            self.startup_toggle.setChecked(not enable)
        else:
            self.startup_enabled = enable
            self.cfg["startup"] = enable
            save_config(self.cfg)
            self.log(f"Startup {'enabled' if enable else 'disabled'}")

    def _set_startup(self, enable: bool):
        if winreg is None:
            return False, "winreg not available on this platform"
        try:
            exe = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
            exe = str(Path(exe).resolve())
            name = "MultiDownloader"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS) as key:
                if enable:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, exe)
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
            return True, "ok"
        except Exception as e:
            return False, str(e)

    # ---------- Logging ----------
    def log(self, *parts):
        try:
            s = " ".join(str(p) for p in parts)
            self.log_text.append(s)
            self.status_label.setText(s)
        except Exception:
            pass

    # ---------- Clipboard check ----------
    def _check_clipboard(self):
        try:
            cb = QApplication.clipboard()
            txt = cb.text().strip()
            if txt and txt != self.clip_last:
                low = txt.lower()
                if any(d in low for d in SUPPORTED_DOMAINS) and ("\n" not in txt):
                    self.clip_last = txt
                    resp = QMessageBox.question(self, "Clipboard URL detected",
                                                f"Detected URL in clipboard:\n{txt}\n\nDownload now (Best)?",
                                                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                    if resp == QMessageBox.Yes:
                        self.urls_text.setPlainText(txt)
                        self.cookies_edit.setText(self.cookies_edit.text().strip())
                        self.on_direct_download()
                    elif resp == QMessageBox.No:
                        self.urls_text.setPlainText(txt)
                        self.on_fetch_info()
                        self.show_window()
                    else:
                        pass
                else:
                    self.clip_last = txt
        except Exception:
            pass

    # ---------- File/CSV ----------
    def on_load_csv(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open CSV / TXT with URLs (one per line)", "", "Text Files (*.txt *.csv);;All Files (*)")
        if not f:
            return
        try:
            txt = Path(f).read_text(encoding="utf-8")
            self.urls_text.setPlainText(txt)
            QMessageBox.information(self, "Loaded", "Loaded URLs into input area.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load file: {e}")

    def on_browse_cookies(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt (Netscape)", "", "Text Files (*.txt);;All Files (*)")
        if f:
            self.cookies_edit.setText(f)
            self.cfg["cookies"] = f
            save_config(self.cfg)
            self.log("Using cookies:", f)

    def on_change_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select download folder", str(self.download_dir))
        if d:
            self.download_dir = Path(d)
            self.folder_label.setText(str(self.download_dir))
            self.cfg["download_dir"] = str(self.download_dir)
            save_config(self.cfg)
            self.log("Download folder set:", d)

    # ---------- Fetch info ----------
    def on_fetch_info(self):
        txt = self.urls_text.toPlainText().strip()
        if not txt:
            QMessageBox.information(self, "No URL", "Paste at least one URL.")
            return
        url = normalize_url(txt.splitlines()[0].strip())
        self._fetch_and_show(url)

    def _fetch_and_show(self, url):
        self.log("Fetching info for", url)
        self.status_label.setText("Fetching info...")
        QApplication.processEvents()
        try:
            import yt_dlp
        except Exception:
            QMessageBox.warning(self, "Missing", "yt-dlp not installed. Install: pip install yt-dlp")
            return
        opts = {"quiet": True, "no_warnings": True}
        cookies = self.cookies_edit.text().strip()
        if cookies:
            opts["cookiefile"] = cookies
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            title = info.get("title") or info.get("id") or url
            uploader = info.get("uploader") or info.get("channel") or ""
            duration = seconds_to_hhmmss(info.get("duration") or 0)
            self.meta_label.setText(f"<b>{title}</b>\n{uploader}\nDuration: {duration}")
            thumb = info.get("thumbnail")
            if thumb:
                pix = thumbnail_pixmap_from_url(thumb, max_w=360)
                if pix:
                    self.thumb_label.setPixmap(pix.scaled(self.thumb_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            # populate formats
            formats = info.get("formats", []) or []
            friendly = []
            seen = set()
            for f in formats:
                key = (f.get("height"), f.get("abr"), f.get("ext"))
                if key in seen:
                    continue
                seen.add(key)
                size = f.get("filesize") or f.get("filesize_approx") or 0
                if f.get("vcodec") and f.get("vcodec") != "none":
                    label = f"{f.get('height') or ''}p [{f.get('ext')}] ({friendly_size(size)})"
                elif f.get("acodec") and (not f.get("vcodec") or f.get("vcodec") == "none"):
                    label = f"audio {f.get('abr') or ''}kbps [{f.get('ext')}] ({friendly_size(size)})"
                else:
                    label = f.get("format_note") or f.get("format") or f.get("ext")
                friendly.append((label, f.get("format_id")))
            self.format_combo.clear()
            for lbl, fid in friendly:
                self.format_combo.addItem(lbl, fid)
            self.format_combo.setEnabled(len(friendly) > 0)
            self.best_checkbox.setEnabled(True)
            self.status_label.setText("Info fetched.")
            self.log("Formats fetched:", len(friendly))
        except Exception as e:
            msg = str(e)
            self.log("Fetch failed:", msg)
            self.meta_label.setText("Failed to fetch: " + msg)
            self.status_label.setText("Fetch failed")
            if "no video" in msg.lower() or "there is no video" in msg.lower():
                QMessageBox.information(self, "No video", "No video found — likely image-only post. gallery-dl fallback will be used when downloading (cookies may be required).")

    # ---------- Direct download ----------
    def on_direct_download(self):
        txt = self.urls_text.toPlainText().strip()
        if not txt:
            QMessageBox.information(self, "No URL", "Paste at least one URL.")
            return
        urls = [normalize_url(u.strip()) for u in txt.splitlines() if u.strip()]
        self.batch_total = len(urls)
        self.batch_done = 0
        self.overall_progress.setValue(0)
        self._start_batch(urls, use_best=True)

    # ---------- Choose & download ----------
    def on_choose_and_download(self):
        txt = self.urls_text.toPlainText().strip()
        if not txt:
            QMessageBox.information(self, "No URL", "Paste at least one URL.")
            return
        url = normalize_url(txt.splitlines()[0].strip())
        self._fetch_and_show(url)
        # if no formats, offer gallery-dl
        if self.format_combo.count() == 0:
            ans = QMessageBox.question(self, "No formats", "No video/audio formats detected. Try gallery-dl fallback?", QMessageBox.Yes | QMessageBox.No)
            if ans == QMessageBox.Yes:
                self._run_gallery_dl(url)
            return
        # pick current selection
        fid = self.format_combo.currentData()
        use_best = self.best_checkbox.isChecked()
        s = self.start_time_edit.text().strip()
        e = self.end_time_edit.text().strip()
        sections = None
        if s and e and s != e:
            sections = [{"start_time": s, "end_time": e}]
        self._start_batch([url], use_best=use_best, format_id=fid, sections=sections)

    # ---------- Start batch processing ----------
    def _start_batch(self, urls, use_best=True, format_id=None, sections=None):
        self.queue = list(urls)
        self.batch_total = len(self.queue)
        self.batch_done = 0
        self.overall_progress.setValue(0)
        # process sequentially to keep things simple
        QtCore.QTimer.singleShot(50, lambda: self._process_next_in_queue(use_best, format_id, sections))

    def _process_next_in_queue(self, use_best, format_id, sections):
        if not self.queue:
            self.log("Batch complete.")
            self.status_label.setText("All done.")
            return
        url = self.queue.pop(0)
        self.log("Processing:", url)
        # detect content type with yt-dlp info; lazy import
        try:
            import yt_dlp
        except Exception:
            QMessageBox.warning(self, "Missing", "yt-dlp not installed.")
            return
        opts = {"quiet": True, "no_warnings": True}
        cookies = self.cookies_edit.text().strip()
        if cookies:
            opts["cookiefile"] = cookies
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats") or []
            has_video = any((f.get("vcodec") and f.get("vcodec") != "none") for f in formats)
            has_audio = any((f.get("acodec") and f.get("acodec") != "none") for f in formats)
            if has_video or has_audio:
                # start yt-dlp worker
                self._start_worker(url, use_best=use_best, format_id=format_id, sections=sections)
            else:
                # image/gallery -> gallery-dl
                self.log("Image/gallery detected — using gallery-dl")
                self._start_gallery(url)
        except Exception as e:
            msg = str(e)
            if "no video" in msg.lower() or "there is no video" in msg.lower() or "unsupported url" in msg.lower():
                self.log("No video detected — trying gallery-dl fallback.")
                self._start_gallery(url)
            elif "requested format is not available" in msg.lower():
                self.log("Requested format not available — falling back to best.")
                self._start_worker(url, use_best=True, format_id=None, sections=sections)
            else:
                self.log("Error detecting content:", msg)
                # mark as done and continue
                self.batch_done += 1
                self._update_overall_progress()
                QtCore.QTimer.singleShot(200, lambda: self._process_next_in_queue(use_best, format_id, sections))

    # ---------- Start yt-dlp worker ----------
    def _start_worker(self, url, use_best=True, format_id=None, sections=None):
        self.status_label.setText("Starting yt-dlp...")
        self.item_target_pct = 0.0
        self.item_display_pct = 0.0
        self.item_progress.setValue(0)
        self.current_worker = YTDLPWorker(url, self.download_dir, format_id=format_id,
                                          cookies=self.cookies_edit.text().strip() or None,
                                          proxy=self.proxy, sections=sections,
                                          retries=3, use_best=use_best)
        self.current_worker.progress.connect(self._on_item_progress)
        self.current_worker.status.connect(lambda s: self.log(s))
        self.current_worker.finished.connect(self._on_worker_finished)
        self.current_worker.start()

    def _on_item_progress(self, pct, info):
        # update target percent and show info (speed)
        try:
            self.item_target_pct = float(pct)
        except Exception:
            self.item_target_pct = 0.0
        if info:
            self.status_label.setText(f"{pct:.1f}% {info}")
        self.log(f"Progress: {pct:.1f}% {info}")

    def _animate_item_progress(self):
        # interpolate displayed percent toward target for smooth animation
        try:
            diff = self.item_target_pct - self.item_display_pct
            step = max(0.5, abs(diff) * 0.2)
            if abs(diff) < 0.01:
                self.item_display_pct = self.item_target_pct
            else:
                self.item_display_pct += step if diff > 0 else -step
            self.item_progress.setValue(int(self.item_display_pct))
        except Exception:
            pass

    def _on_worker_finished(self, res):
        if res.get("ok"):
            self.log("Downloaded:", res.get("url"))
            QMessageBox.information(self, "Downloaded", f"Saved: {res.get('url')}")
        else:
            err = res.get("error") or ""
            self.log("Worker failed:", err)
            # if failure looks like no video, attempt gallery-dl
            if "no video" in err.lower() or "there is no video" in err.lower() or "unsupported url" in err.lower():
                self.log("Attempting gallery-dl fallback...")
                self._start_gallery(res.get("url"))
                return
            elif "requested format is not available" in err.lower():
                self.log("Format unavailable — retrying with best quality")
                self._start_worker(res.get("url"), use_best=True)
                return
            else:
                QMessageBox.warning(self, "Download failed", err)
        # update batch progress and move next
        self.batch_done += 1
        self._update_overall_progress()
        QtCore.QTimer.singleShot(200, lambda: self._process_next_in_queue(self.best_checkbox.isChecked(), self.format_combo.currentData(), None))

    # ---------- Start gallery-dl worker ----------
    def _start_gallery(self, url):
        self.gallery_worker = GalleryDLWorker(url, self.download_dir, cookies=self.cookies_edit.text().strip() or None)
        self.gallery_worker.status.connect(lambda s: self.log(s))
        self.gallery_worker.finished.connect(self._on_gallery_finished)
        self.gallery_worker.start()

    def _on_gallery_finished(self, res):
        if res.get("ok"):
            self.log("gallery-dl success:", res.get("out"))
            QMessageBox.information(self, "gallery-dl", res.get("out") or "gallery-dl finished")
        else:
            out = res.get("out") or ""
            self.log("gallery-dl failed:", out)
            if "redirect to login" in out.lower() or "login" in out.lower():
                QMessageBox.warning(self, "Login required", "gallery-dl indicates login required. Provide cookies.txt in Cookies field.")
            else:
                QMessageBox.warning(self, "gallery-dl failed", out)
        self.batch_done += 1
        self._update_overall_progress()
        QtCore.QTimer.singleShot(200, lambda: self._process_next_in_queue(self.best_checkbox.isChecked(), self.format_combo.currentData(), None))

    # ---------- Overall progress ----------
    def _update_overall_progress(self):
        try:
            if self.batch_total <= 0:
                self.overall_progress.setValue(0)
                return
            pct = int((self.batch_done / self.batch_total) * 100)
            self.overall_progress.setValue(pct)
            self.log(f"Batch {self.batch_done}/{self.batch_total}")
        except Exception:
            pass

    # ---------- gallery-dl direct run helper ----------
    def _run_gallery_dl(self, url):
        # Synchronous helper (used for simple calls)
        try:
            cmd = ["gallery-dl", "-d", str(self.download_dir), url]
            cookies = self.cookies_edit.text().strip()
            if cookies:
                cmd.extend(["--cookies", cookies])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if proc.returncode == 0:
                return True, proc.stdout.strip() or "gallery-dl finished"
            else:
                return False, (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        except FileNotFoundError:
            return False, "gallery-dl not found"
        except subprocess.TimeoutExpired:
            return False, "gallery-dl timeout"
        except Exception as e:
            return False, f"gallery-dl error: {e}"

# -------------- Entrypoint --------------
def main():
    app = QApplication(sys.argv)
    # single instance guard (basic)
    if QtWidgets.QApplication.instance() is not None:
        pass
    win = MultiDownloader()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
