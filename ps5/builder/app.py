"""PS5 Longshot Plus Builder, the window."""
import ftplib
import os
import signal
import subprocess
import sys

from PyQt6.QtCore import QSettings, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QIcon, QPixmap, QTextCursor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.environ.get("LONGSHOT_PS5_PIPELINE", os.path.join(HERE, "pipeline.py"))
STEPS = ["Reading the game's program", "Translating it to C", "Compiling for the console", "Linking", "Making the title folder",
         "Listing the game's shaders", "Extracting the game's data"]
ABOUT = {
    1: "A few seconds.",
    2: "5 to 15 minutes. About 2 GB of memory, more to go faster where it is free.",
    3: "The long step: 30 to 60 minutes on a 6-core PC; 1 to 2 hours with Memory to use at 2 or 3 GB.",
    4: "Under a minute.",
    5: "A few seconds.",
    6: "A few seconds.",
    7: "10 to 40 minutes: every game file (about 26 GB) into the title folder: 53 packs in Data/ and Data.idx (loose files "
       "with Game data as a folder). Wants that much free on its drive.",
}

STYLE = """
QWidget { background-color: #0D1117; color: #E6EDF3; font-size: 13px; }
QFrame#Card { background-color: #161B22; border: 1px solid #30363D; border-radius: 10px; }
QLabel { background: transparent; }
QLabel#FieldLabel { color: #C9D1D9; font-weight: 600; }
QLabel#SubTitle { color: #8B949E; font-size: 12px; }
QLabel#Badge { background-color: #1F3A5F; color: #58A6FF; border: 1px solid #388BFD; border-radius: 6px; padding: 3px 8px; font-weight: bold; font-size: 11px; }
QLineEdit, QComboBox, QSpinBox { background-color: #0D1117; color: #F0F6FC; border: 1px solid #30363D; border-radius: 6px; padding: 5px 10px; min-height: 24px; selection-background-color: #0070D1; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #388BFD; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background-color: #161B22; color: #6E7681; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background-color: #161B22; color: #F0F6FC; border: 1px solid #30363D; selection-background-color: #0070D1; }
QPushButton { background-color: #21262D; color: #E6EDF3; border: 1px solid #30363D; border-radius: 6px; padding: 6px 14px; min-height: 24px; font-weight: 600; }
QPushButton:hover { background-color: #30363D; border-color: #8B949E; }
QPushButton:disabled { background-color: #161B22; color: #484F58; border-color: #21262D; }
QPushButton#PrimaryBtn { background-color: #0070D1; color: #FFFFFF; border: 1px solid #1A85E8; padding: 7px 22px; }
QPushButton#PrimaryBtn:hover { background-color: #1A85E8; }
QPushButton#StopBtn { background-color: #DA3633; color: #FFFFFF; border: 1px solid #F85149; padding: 7px 22px; }
QPushButton#StopBtn:hover { background-color: #F85149; }
QPushButton#SendBtn { background-color: #238636; color: #FFFFFF; border: 1px solid #2EA043; }
QPushButton#SendBtn:hover { background-color: #2EA043; }
QPushButton#SendBtn:disabled { background-color: #161B22; color: #484F58; border-color: #21262D; }
QProgressBar { background-color: #0D1117; border: 1px solid #30363D; border-radius: 6px; height: 12px; text-align: center; color: transparent; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0070D1, stop:1 #00D2FF); border-radius: 5px; }
QPlainTextEdit { background-color: #090C10; color: #C9D1D9; border: 1px solid #30363D; border-radius: 6px; padding: 6px; }
QCheckBox { color: #C9D1D9; spacing: 8px; }
"""


def python_exe():
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(console):
            return console
    return exe


class Build(QThread):
    line = pyqtSignal(str)
    ended = pyqtSignal(int)

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.proc = None
        self.failed_to_start = ""

    def run(self):
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kw = {"startupinfo": si, "creationflags": subprocess.CREATE_NEW_CONSOLE}
        else:
            kw = {"start_new_session": True}
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        try:
            self.proc = subprocess.Popen([python_exe()] + self.args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, env=env, **kw)
        except OSError as e:
            self.failed_to_start = str(e)
            self.ended.emit(-1)
            return
        for raw in self.proc.stdout:
            self.line.emit(raw.decode("utf-8", "replace").rstrip("\r\n"))
        self.ended.emit(self.proc.wait())

    def stop(self):
        p = self.proc
        if not p or p.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()


class Sender(QThread):
    progress = pyqtSignal(int, int)
    said = pyqtSignal(str)
    ended = pyqtSignal(str)

    def __init__(self, folder, host, port):
        super().__init__()
        self.folder, self.host, self.port = folder, host, port

    def run(self):
        try:
            title = os.path.basename(self.folder.rstrip("/\\"))
            files = []
            for base, _, names in os.walk(self.folder):
                for n in names:
                    p = os.path.join(base, n)
                    files.append((p, os.path.relpath(p, self.folder).replace(os.sep, "/")))
            # (the executable last, and last of all the mark that Data/ is whole: a send stopped part way leaves no folder
            # that looks complete)
            files.sort(key=lambda f: (f[1] in ("Data.idx", "longshot_data.txt"), f[1] == "longshot_data.txt",
                                      f[1] in ("eboot.bin", "sce_sys/param.json"), f[1]))
            total = sum(os.path.getsize(p) for p, _ in files)
            sent = 0
            ftp = None
            payload_ports = {7070, 9020, 9021, 9090}
            candidates = [] if self.port in payload_ports else [self.port]
            for cand in (2121, 1337):
                if cand not in candidates:
                    candidates.append(cand)
            last_err = None
            for cand in candidates:
                try:
                    c = ftplib.FTP()
                    c.connect(self.host, cand, timeout=5)
                    c.login()
                    ftp = c
                    if cand != self.port:
                        self.said.emit(f"Connected via auto-detected FTP port {cand}…")
                    break
                except Exception as exc:
                    last_err = exc
            if ftp is None:
                if self.port in payload_ports:
                    raise ConnectionError(
                        f"Port {self.port} is a payload receiver, not an FTP server. "
                        f"Enable FTP Server in etaHEN / Itemzflow / Prospero Mgr (or inject ftpsrv.elf) "
                        f"so port 2121 or 1337 is active."
                    )
                raise last_err
            ftp.voidcmd("TYPE I")
            root = "/data/homebrew/" + title

            made = set()

            def mkdirs(path):   # (each folder asked for once: Data/ holds about 186,000 files)
                at = ""
                for part in path.strip("/").split("/"):
                    at += "/" + part
                    if at in made:
                        continue
                    try:
                        ftp.mkd(at)
                    except ftplib.all_errors:
                        pass
                    made.add(at)
            mkdirs(root)
            for path, rel in files:
                if "/" in rel:
                    mkdirs(root + "/" + rel.rsplit("/", 1)[0])
                self.said.emit("sending " + rel)
                with open(path, "rb") as f:
                    def block(b):
                        nonlocal sent
                        sent += len(b)
                        self.progress.emit(sent >> 10, max(1, total >> 10))
                    ftp.storbinary("STOR " + root + "/" + rel, f, blocksize=1 << 20, callback=block)
            try:
                ftp.quit()
            except ftplib.all_errors:
                pass
            self.ended.emit("")
        except Exception as e:
            self.ended.emit("%s: %s" % (type(e).__name__, e))


def _builder_version():
    for rel in ("../VERSION", "VERSION"):
        vp = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
        if os.path.isfile(vp):
            v = open(vp).read().strip()
            if v:
                return v if v.startswith("v") else f"v{v}"
    try:
        v = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if v:
            return v if v.startswith("v") else f"v{v}"
    except Exception:
        pass
    return "v0.3.4-plus"


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PS5 Longshot Plus Builder")
        icon_path = os.path.join(HERE, "longshot.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.settings = QSettings("PS5_Longshot", "Builder")
        self.proc = None
        self.sender = None
        self.built = ""
        self.stopping = False
        self.error = ""
        self.current = 0

        header_row = QHBoxLayout()
        header_row.setSpacing(14)
        if os.path.exists(icon_path):
            logo = QLabel()
            logo.setPixmap(QPixmap(icon_path).scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            header_row.addWidget(logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title_line = QHBoxLayout()
        head = QLabel("PS5 Longshot Plus Builder")
        f = QFont(self.font())
        f.setPointSize(f.pointSize() + 6)
        f.setBold(True)
        head.setFont(f)
        badge = QLabel(f"{_builder_version()} • PS5 Fat / Slim & Pro")
        badge.setObjectName("Badge")
        title_line.addWidget(head)
        title_line.addWidget(badge)
        title_line.addStretch(1)
        sub = QLabel("Builds the PlayStation 5 title folder (PPSA99198) locally from your own copy of the game. Never share the output folder.")
        sub.setObjectName("SubTitle")
        sub.setWordWrap(True)
        title_col.addLayout(title_line)
        title_col.addWidget(sub)
        header_row.addLayout(title_col, 1)

        cfg_card = QFrame()
        cfg_card.setObjectName("Card")
        grid = QGridLayout(cfg_card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        def lbl(text):
            l = QLabel(text)
            l.setObjectName("FieldLabel")
            return l

        self.game = QLineEdit(self.settings.value("game", ""))
        self.game.setPlaceholderText("Select your game file (.nup)")
        self.game_pick = QPushButton("Choose…")
        self.game_pick.setFixedWidth(105)
        self.game_pick.clicked.connect(self.pick_game)
        grid.addWidget(lbl("Game file (.nup)"), 0, 0)
        grid.addWidget(self.game, 0, 1, 1, 3)
        grid.addWidget(self.game_pick, 0, 4)

        self.out = QLineEdit(self.settings.value("out", os.path.join(os.path.expanduser("~"), "PS5-Longshot-Plus")))
        self.out.setPlaceholderText("Destination folder on this computer")
        self.out_pick = QPushButton("Choose…")
        self.out_pick.setFixedWidth(105)
        self.out_pick.clicked.connect(self.pick_out)
        grid.addWidget(lbl("Build into"), 1, 0)
        grid.addWidget(self.out, 1, 1, 1, 3)
        grid.addWidget(self.out_pick, 1, 4)

        self.model = QComboBox()
        self.model.addItem("Choose your console…", "")
        self.model.addItem("PS5 / PS5 Slim (Base 12 GB)", "base")
        self.model.addItem("PS5 Pro (Expanded 13.2 GB)", "pro")
        self.model.setCurrentIndex(max(0, self.model.findData(self.settings.value("model", ""))))

        self.memory = QComboBox()
        self.memory.addItem("Automatic (free RAM)", 0)
        for gb in (2, 3, 4, 6, 8, 12, 16):
            self.memory.addItem("%d GB" % gb, gb)
        self.memory.setCurrentIndex(max(0, self.memory.findData(int(self.settings.value("memory", 0)))))

        self.jobs = QSpinBox()
        self.jobs.setRange(0, 64)
        self.jobs.setSpecialValueText("Auto cores")
        self.jobs.setValue(int(self.settings.value("jobs", 0)))

        grid.addWidget(lbl("Console model"), 2, 0)
        grid.addWidget(self.model, 2, 1)
        grid.addWidget(lbl("Memory / Cores"), 2, 2)
        mem_cores = QHBoxLayout()
        mem_cores.setSpacing(8)
        mem_cores.addWidget(self.memory, 1)
        mem_cores.addWidget(self.jobs)
        grid.addLayout(mem_cores, 2, 3, 1, 2)
        # (the game's data as packs with an index by default: ps5/builder/data_packs.py; as loose files for mods)
        self.data_folder = QCheckBox("Game data as a folder (loose files, for mods): takes 2-3x the room on exFAT drives")
        self.data_folder.setChecked(str(self.settings.value("data_folder", "false")).lower() == "true")
        grid.addWidget(self.data_folder, 3, 1, 1, 4)
        # (the shaders of known_gpu_hangs.txt left out, RX_VK_GPU_SKIP in longshot_env.txt: on unless turned off)
        self.known_skips = QCheckBox("Skip shaders known to hang the GPU (what they draw there is missing)")
        self.known_skips.setChecked(str(self.settings.value("known_skips", "true")).lower() == "true")
        grid.addWidget(self.known_skips, 4, 1, 1, 4)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(3, 2)

        prog_card = QFrame()
        prog_card.setObjectName("Card")
        steps_box = QVBoxLayout(prog_card)
        steps_box.setContentsMargins(16, 14, 16, 14)
        steps_box.setSpacing(6)
        self.steps = []
        for i, name in enumerate(STEPS, 1):
            l = QLabel()
            l.setTextFormat(Qt.TextFormat.RichText)
            self.steps.append(l)
            steps_box.addWidget(l)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        steps_box.addSpacing(4)
        steps_box.addWidget(self.bar)

        self.status = QLabel("Ready — choose your .nup file and console profile, then press Build Title.")
        self.status.setStyleSheet("color: #58A6FF; font-weight: 600;")
        self.status.setWordWrap(True)
        steps_box.addWidget(self.status)

        self.go = QPushButton("Build Title")
        self.go.setObjectName("PrimaryBtn")
        self.go.setDefault(True)
        self.go.clicked.connect(self.start_or_stop)
        self.open = QPushButton("Open Output Folder")
        self.open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.built)))
        self.open.setEnabled(False)
        self.details = QCheckBox("Show build log")
        self.details.toggled.connect(lambda on: self.log.setVisible(on))

        buttons = QHBoxLayout()
        buttons.addWidget(self.details)
        buttons.addStretch(1)
        buttons.addWidget(self.open)
        buttons.addWidget(self.go)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        mono = QFont("Menlo" if sys.platform == "darwin" else "monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.log.setFont(mono)
        self.log.setVisible(False)
        self.log.setMinimumHeight(160)

        ftp_card = QFrame()
        ftp_card.setObjectName("Card")
        ftp_box = QVBoxLayout(ftp_card)
        ftp_box.setContentsMargins(16, 12, 16, 12)
        ftp_box.setSpacing(8)
        self.send_note = QLabel("After building: copy <b>PPSA99198</b> to <b>/data/homebrew/</b> on your PS5 (or send over FTP below). The game's data is in <b>Data</b> and <b>Data.idx</b> (about 26 GB): the console needs no .nup.")
        self.send_note.setObjectName("SubTitle")
        self.send_note.setWordWrap(True)
        self.send_note.setTextFormat(Qt.TextFormat.RichText)

        self.ps5 = QLineEdit(self.settings.value("ps5", ""))
        self.ps5.setPlaceholderText("PS5 IP address (e.g. 192.168.1.50)")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(self.settings.value("port", 2121)))
        self.send = QPushButton("Send to PS5")
        self.send.setObjectName("SendBtn")
        self.send.setEnabled(False)
        self.send.clicked.connect(self.start_send)

        send_row = QHBoxLayout()
        send_row.setSpacing(10)
        send_row.addWidget(lbl("PS5 FTP IP"))
        send_row.addWidget(self.ps5, 1)
        send_row.addWidget(lbl("Port"))
        send_row.addWidget(self.port)
        send_row.addWidget(self.send)

        ftp_box.addWidget(self.send_note)
        ftp_box.addLayout(send_row)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(12)
        box.addLayout(header_row)
        box.addWidget(cfg_card)
        box.addWidget(prog_card)
        box.addLayout(buttons)
        box.addWidget(self.log, 1)
        box.addWidget(ftp_card)
        self.resize(820, 620)
        self.setMinimumWidth(760)
        self.show_steps(0)

    def show_steps(self, current, failed=False, done=False):
        for i, l in enumerate(self.steps, 1):
            name = STEPS[i - 1]
            if done or i < current:
                l.setText("<span style='color:#3FB950; font-weight:bold'>✓</span> <span style='color:#E6EDF3'>%s</span>" % name)
            elif i == current:
                mark = "<span style='color:#F85149; font-weight:bold'>✗</span>" if failed else "<span style='color:#00D2FF; font-weight:bold'>▸</span>"
                l.setText("%s <b style='color:#FFFFFF'>%s</b> <span style='color:#8B949E'>— %s</span>" % (mark, name, "" if failed else ABOUT.get(i, "")))
            else:
                l.setText("<span style='color:#484F58'>○</span> <span style='color:#8B949E'>%s</span>" % name)
        self.current = current

    def pick_game(self):
        start = os.path.dirname(self.game.text()) or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Your game file", start, "Game files (*.nup);;All files (*)")
        if path:
            self.game.setText(path)

    def pick_out(self):
        path = QFileDialog.getExistingDirectory(self, "Build into", self.out.text() or os.path.expanduser("~"))
        if path:
            self.out.setText(path)

    def busy(self, on):
        for w in (self.game, self.game_pick, self.out, self.out_pick, self.jobs, self.memory, self.model, self.data_folder,
                  self.known_skips):
            w.setEnabled(not on)
        self.go.setText("Stop Build" if on else "Build Title")
        self.go.setObjectName("StopBtn" if on else "PrimaryBtn")
        self.go.style().unpolish(self.go)
        self.go.style().polish(self.go)

    def start_or_stop(self):
        if self.proc:
            if QMessageBox.question(self, "Stop the build?", "Stop the build? What it has done so far is kept: the next "
                                    "build goes on from there.") == QMessageBox.StandardButton.Yes and self.proc:
                self.stopping = True
                self.proc.stop()
            return
        game, out = self.game.text().strip(), self.out.text().strip()
        if not game or not os.path.exists(game):
            QMessageBox.warning(self, "No game file", "Choose your game file first: the .nup of your own copy of the game.")
            return
        if not out:
            QMessageBox.warning(self, "No folder", "Choose the folder to build into.")
            return
        model = self.model.currentData()
        if not model:
            QMessageBox.warning(self, "No console", "Choose your console: PS5 / PS5 Slim, or PS5 Pro.")
            return
        for k, v in (("game", game), ("out", out), ("jobs", self.jobs.value()), ("memory", self.memory.currentData()), ("model", model),
                     ("data_folder", self.data_folder.isChecked()), ("known_skips", self.known_skips.isChecked())):
            self.settings.setValue(k, v)
        os.makedirs(out, exist_ok=True)
        self.log.clear()
        self.built = ""
        self.stopping = False
        self.open.setEnabled(False)
        self.send.setEnabled(False)
        self.bar.setRange(0, 0)
        self.status.setStyleSheet("color: #58A6FF; font-weight: 600;")
        self.status.setText("Building PS5 title folder…")
        self.show_steps(1)
        self.busy(True)
        args = ["-I", "-u", PIPELINE, "--game", game, "--out", out, "--model", model]
        if self.jobs.value():
            args += ["--jobs", str(self.jobs.value())]
        if self.memory.currentData():
            args += ["--memory", str(self.memory.currentData())]
        if self.data_folder.isChecked():
            args += ["--data-folder"]
        if not self.known_skips.isChecked():
            args += ["--no-known-skips"]
        self.error = ""
        self.proc = Build(args)
        self.proc.line.connect(self.line)
        self.proc.ended.connect(self.finished)
        self.proc.start()

    def line(self, line):
        if line.startswith("@@step "):
            parts = line.split(" ", 2)
            if len(parts) > 1 and parts[1].isdigit():
                self.show_steps(int(parts[1]))
            if len(parts) > 2:
                self.status.setText(parts[2])
        elif line.startswith("@@progress "):
            nums = line.split()[1:3]
            if len(nums) == 2 and all(x.isdigit() for x in nums):
                a, b = int(nums[0]), int(nums[1])
                self.bar.setRange(0, max(1, b))
                self.bar.setValue(a)
        elif line.startswith("@@done "):
            self.built = line.split(" ", 1)[1].strip()
        elif line.startswith("@@error "):
            self.error = line.split(" ", 1)[1].strip()
        else:
            self.log.appendPlainText(line)

    def fail(self, text):
        self.show_steps(max(1, self.current), failed=True)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.status.setStyleSheet("color: #F85149; font-weight: 600;")
        self.status.setText(text.split("\n")[0])
        self.details.setChecked(True)
        self.log.appendPlainText("\n" + text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def finished(self, code):
        if self.proc and self.proc.failed_to_start:
            self.error = "The builder's own Python did not start (%s): %s" % (python_exe(), self.proc.failed_to_start)
        if self.proc:
            self.proc.wait()
        self.proc = None
        self.busy(False)
        if self.built and code == 0:
            self.show_steps(len(STEPS) + 1, done=True)
            self.bar.setRange(0, 1)
            self.bar.setValue(1)
            self.status.setStyleSheet("color: #3FB950; font-weight: 600;")
            self.status.setText("Done! Your PS5 title folder is ready: %s" % self.built)
            self.open.setEnabled(True)
            self.send.setEnabled(True)
        elif self.stopping:
            self.show_steps(self.current, failed=True)
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            self.status.setStyleSheet("color: #D29922; font-weight: 600;")
            self.status.setText("Stopped. Build again to continue from where it stopped.")
        else:
            self.fail(getattr(self, "error", "") or "The build stopped (exit %d). Check the build log for details." % code)
        self.error = ""

    def start_send(self):
        host = self.ps5.text().strip()
        if not host:
            QMessageBox.warning(self, "No address", "Type the console's address: its IP on your network.")
            return
        self.settings.setValue("ps5", host)
        self.settings.setValue("port", self.port.value())
        self.send.setEnabled(False)
        self.go.setEnabled(False)
        self.status.setStyleSheet("color: #58A6FF; font-weight: 600;")
        self.status.setText("Sending PPSA99198 to the console over FTP…")
        self.sender = Sender(self.built, host, self.port.value())
        self.sender.progress.connect(lambda a, b: (self.bar.setRange(0, b), self.bar.setValue(a)))
        self.sender.said.connect(self.log.appendPlainText)
        self.sender.ended.connect(self.sent)
        self.sender.start()

    def sent(self, error):
        self.send.setEnabled(True)
        self.go.setEnabled(True)
        if error:
            self.status.setStyleSheet("color: #F85149; font-weight: 600;")
            self.status.setText("Not sent: %s" % error)
            QMessageBox.warning(self, "Not sent", "The folder was not sent to the console.\n\n%s\n\nIs the console on, with its "
                                "FTP server running, at this address and port?" % error)
        else:
            self.status.setStyleSheet("color: #3FB950; font-weight: 600;")
            self.status.setText("Sent! %s is now in /data/homebrew on your PS5." % os.path.basename(self.built))

    def closeEvent(self, e):
        if self.proc:
            if QMessageBox.question(self, "Stop the build?", "A build is running. Stop it and close?") != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.proc.stop()
            self.proc.wait(5000)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setApplicationName("PS5 Longshot Plus Builder")
    w = Window()
    w.show()
    if "--self-test" in sys.argv:
        from PyQt6.QtCore import QTimer
        result = {"code": 1}
        log = []
        check = Build(["-I", "-u", PIPELINE, "--check"])
        check.line.connect(lambda line: (log.append(line), print(line, flush=True)))
        check.ended.connect(lambda code: (result.update(code=0 if code == 0 and any(l == "@@done check" for l in log) else 1), app.quit()))
        QTimer.singleShot(200, check.start)
        QTimer.singleShot(240000, app.quit)
        app.exec()
        check.wait(5000)
        print("self-test: the window opened (%dx%d), the check %s" % (w.width(), w.height(), "passed" if result["code"] == 0 else "FAILED"), flush=True)
        return result["code"]
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
