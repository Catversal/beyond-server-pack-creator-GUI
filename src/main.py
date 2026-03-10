import sys
import os
import json
import shutil
import zipfile
import urllib.request
import threading
import subprocess
import platform

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QComboBox,
    QTextEdit, QProgressBar, QTabWidget, QGroupBox, QCheckBox,
    QSpinBox, QMessageBox, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon

# ─────────────────────────────────────────────────
#  Paths
# ─────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_DIR   = os.path.join(BASE_DIR, "config")
MAP_FILE     = os.path.join(CONFIG_DIR, "modpack_map.txt")
REMOVE_DIR   = os.path.join(CONFIG_DIR, "remove_list")
GIT_ZIP_URL  = "https://github.com/Catversal/beyond-forge-server-creator/archive/refs/heads/main.zip"

# ─────────────────────────────────────────────────
#  Helper – read modpack_map.txt
# ─────────────────────────────────────────────────

def load_modpack_map():
    packs = []
    if not os.path.isfile(MAP_FILE):
        return packs
    with open(MAP_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                packs.append({
                    "id":      parts[0].strip(),
                    "name":    parts[1].strip(),
                    "match":   parts[2].strip(),
                    "mc":      parts[3].strip(),
                    "flag":    parts[4].strip(),
                })
    return packs


def parse_manifest(client_pack_path):
    manifest_path = os.path.join(client_pack_path, "manifest.json")
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    name    = data.get("name", "")
    version = data.get("version", "")
    mc_ver  = (data.get("minecraft") or {}).get("version", "")
    forge   = ""
    for ml in (data.get("minecraft") or {}).get("modLoaders") or []:
        mid = (ml or {}).get("id", "")
        if isinstance(mid, str) and mid.startswith("forge-"):
            forge = mid.split("forge-", 1)[1]
            break
    return {"name": name, "version": version, "mc": mc_ver, "forge": forge}


# ─────────────────────────────────────────────────
#  Worker thread
# ─────────────────────────────────────────────────

class WorkerThread(QThread):
    log        = pyqtSignal(str)
    progress   = pyqtSignal(int)
    finished   = pyqtSignal(bool, str)

    def __init__(self, task, **kwargs):
        super().__init__()
        self.task   = task
        self.kwargs = kwargs

    def run(self):
        try:
            if self.task == "update_config":
                self._update_config()
            elif self.task == "create_serverpack":
                self._create_serverpack(**self.kwargs)
        except Exception as e:
            self.finished.emit(False, str(e))

    # ── Config update ──────────────────────────────
    def _update_config(self):
        self.log.emit("📡 Downloading latest config from GitHub…")
        self.progress.emit(10)

        tmp = os.path.join(BASE_DIR, "temp_download")
        os.makedirs(tmp, exist_ok=True)
        zip_path = os.path.join(tmp, "config_update.zip")

        urllib.request.urlretrieve(GIT_ZIP_URL, zip_path)
        self.progress.emit(50)
        self.log.emit("📦 Extracting…")

        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp)

        self.progress.emit(70)

        new_cfg = os.path.join(tmp, "beyond-forge-server-creator-main",
                               "Serverpack-Creator", "config")
        if os.path.isdir(CONFIG_DIR):
            self.log.emit("🗑  Removing old config…")
            shutil.rmtree(CONFIG_DIR)

        shutil.move(new_cfg, CONFIG_DIR)
        shutil.rmtree(tmp)

        self.progress.emit(100)
        self.log.emit("✅ Config updated successfully!")
        self.finished.emit(True, "Config updated!")

    # ── Serverpack creation ────────────────────────
    def _create_serverpack(self, client_pack, modpack_info, manifest,
                            hosting_type, install_forge,
                            server_props, ram_gb, jvm_args, accept_eula):

        pack_name = modpack_info["name"]
        version   = manifest["version"]
        mc_ver    = manifest["mc"]
        forge_ver = manifest["forge"]
        mod_id    = modpack_info["id"]
        copy_tacz = modpack_info["flag"] == "1"

        # ── Output folder ─────────────────────────
        base_name = f"{pack_name}_{version}"
        count = 1
        while True:
            out_dir = os.path.join(BASE_DIR, f"{base_name}_{count}")
            if not os.path.exists(out_dir):
                break
            count += 1
        os.makedirs(out_dir)
        self.log.emit(f"📁 Created folder: {out_dir}")
        self.progress.emit(5)

        # ── Copy folders ──────────────────────────
        folders = ["config", "kubejs", "defaultconfigs", "mods"]
        if copy_tacz:
            folders += ["tacz", "tacz_backup"]

        total = len(folders)
        for i, folder in enumerate(folders):
            src = os.path.join(client_pack, folder)
            dst = os.path.join(out_dir, folder)
            if os.path.isdir(src):
                self.log.emit(f"📋 Copying {folder}…")
                shutil.copytree(src, dst, dirs_exist_ok=True)
            progress_val = 5 + int(((i + 1) / total) * 35)
            self.progress.emit(progress_val)

        # ── Enable server fix mod (modpack id=1) ──
        if mod_id == "1":
            disabled = os.path.join(out_dir, "mods", "Indestructible Server Fix-1.0.jar.disabled")
            if os.path.isfile(disabled):
                os.rename(disabled, disabled[:-len(".disabled")])
                self.log.emit("🔧 Enabled: Indestructible Server Fix")

        self.progress.emit(45)

        # ── Remove client-only mods ───────────────
        remove_file = os.path.join(REMOVE_DIR, self._remove_filename(pack_name))
        if os.path.isfile(remove_file):
            self.log.emit("🗑  Removing client-only mods…")
            mods_dir = os.path.join(out_dir, "mods")
            with open(remove_file, encoding="utf-8") as f:
                for line in f:
                    prefix = line.strip().rstrip("\r")
                    if not prefix:
                        continue
                    for fname in os.listdir(mods_dir):
                        if fname.startswith(prefix) and fname.endswith(".jar"):
                            os.remove(os.path.join(mods_dir, fname))
                            self.log.emit(f"  [DEL] {fname}")
        self.progress.emit(55)

        # ── Forge install ─────────────────────────
        if install_forge and hosting_type == "local":
            self.log.emit(f"⬇️  Downloading Forge {mc_ver}-{forge_ver}…")
            forge_jar  = os.path.join(out_dir, f"forge-{mc_ver}-{forge_ver}-installer.jar")
            forge_url  = (f"https://maven.minecraftforge.net/net/minecraftforge/forge/"
                          f"{mc_ver}-{forge_ver}/forge-{mc_ver}-{forge_ver}-installer.jar")
            urllib.request.urlretrieve(forge_url, forge_jar)
            self.log.emit("🔨 Running Forge installer --installServer…")
            self.progress.emit(70)
            result = subprocess.run(
                ["java", "-jar", forge_jar, "--installServer"],
                cwd=out_dir, capture_output=True, text=True
            )
            if result.returncode == 0:
                os.remove(forge_jar)
                self.log.emit("✅ Forge installed!")
            else:
                self.log.emit(f"⚠️  Forge install warning: {result.stderr[:200]}")

        self.progress.emit(80)

        # ── server.properties ─────────────────────
        self.log.emit("📝 Writing server.properties…")
        motd = (f"\\u00A74\\u00A7lBeyond Modpack \\u00A76 | \\u00A71{pack_name}\\u00A7r\\n"
                f"\\u00A74by Catversal  \\u00A76      |\\u00A71 {version}")
        props = {**self._default_server_props(), "motd": motd}
        props.update(server_props)

        props_path = os.path.join(out_dir, "server.properties")
        with open(props_path, "w", encoding="utf-8") as f:
            f.write("#Minecraft server properties\n#Generated by ServerPackCreator\n")
            for k, v in props.items():
                f.write(f"{k}={v}\n")

        self.progress.emit(88)

        # ── user_jvm_args.txt ─────────────────────
        xms = max(2, ram_gb // 2)
        jvm_path = os.path.join(out_dir, "user_jvm_args.txt")
        base_jvm = f"-Xmx{ram_gb}G\n-Xms{xms}G\n"
        extra = (
            "-Dterminal.jline=false\n-Dterminal.ansi=true\n"
            "-XX:+UseG1GC\n-XX:+DisableExplicitGC\n-XX:+AlwaysPreTouch\n"
            "-XX:MaxGCPauseMillis=100\n-XX:InitiatingHeapOccupancyPercent=25\n"
            "-XX:G1ReservePercent=20\n-XX:+PerfDisableSharedMem\n"
        ) if jvm_args else ""
        with open(jvm_path, "w", encoding="utf-8") as f:
            f.write(base_jvm + extra)

        # ── eula.txt ──────────────────────────────
        eula_path = os.path.join(out_dir, "eula.txt")
        with open(eula_path, "w", encoding="utf-8") as f:
            f.write(f"eula={'true' if accept_eula else 'false'}\n")

        self.progress.emit(100)
        self.log.emit(f"\n🎉 Serverpack created: {out_dir}")
        self.finished.emit(True, out_dir)

    # ── Helpers ───────────────────────────────────
    @staticmethod
    def _remove_filename(pack_name):
        name_map = {
            "Beyond Ascension":     "beyond_ascension_remove.txt",
            "Beyond Cosmo":         "beyond_cosmos_remove.txt",
            "Beyond Depth":         "beyond_depth_remove.txt",
            "Beyond Depth Insanity":"beyond_depth_insanity_remove.txt",
        }
        return name_map.get(pack_name, "")

    @staticmethod
    def _default_server_props():
        return {
            "allow-flight": "true",
            "allow-nether": "true",
            "broadcast-console-to-ops": "true",
            "broadcast-rcon-to-ops": "true",
            "difficulty": "normal",
            "enable-command-block": "true",
            "enable-jmx-monitoring": "false",
            "enable-query": "false",
            "enable-rcon": "false",
            "enable-status": "true",
            "enforce-secure-profile": "true",
            "enforce-whitelist": "false",
            "entity-broadcast-range-percentage": "100",
            "force-gamemode": "false",
            "function-permission-level": "2",
            "gamemode": "survival",
            "generate-structures": "true",
            "generator-settings": "{}",
            "hardcore": "false",
            "hide-online-players": "false",
            "initial-disabled-packs": "",
            "initial-enabled-packs": "vanilla",
            "level-name": "world",
            "level-seed": "",
            "level-type": "minecraft\\:normal",
            "max-chained-neighbor-updates": "1000000",
            "max-players": "200",
            "max-tick-time": "-1",
            "max-world-size": "29999984",
            "network-compression-threshold": "1024",
            "online-mode": "true",
            "op-permission-level": "4",
            "player-idle-timeout": "0",
            "prevent-proxy-connections": "false",
            "pvp": "true",
            "query.port": "25565",
            "rate-limit": "0",
            "rcon.password": "",
            "rcon.port": "25575",
            "require-resource-pack": "false",
            "resource-pack": "",
            "resource-pack-prompt": "",
            "resource-pack-sha1": "",
            "server-ip": "",
            "server-port": "25565",
            "simulation-distance": "10",
            "spawn-animals": "true",
            "spawn-monsters": "true",
            "spawn-npcs": "true",
            "spawn-protection": "0",
            "sync-chunk-writes": "true",
            "text-filtering-config": "",
            "use-native-transport": "true",
            "view-distance": "20",
            "white-list": "false",
        }


# ─────────────────────────────────────────────────
#  Main Window
# ─────────────────────────────────────────────────

DARK_BG    = "#1e1e2e"
PANEL_BG   = "#2a2a3e"
ACCENT     = "#7c3aed"
ACCENT2    = "#a855f7"
TEXT       = "#e2e8f0"
MUTED      = "#94a3b8"
SUCCESS    = "#22c55e"
WARNING    = "#f59e0b"
DANGER     = "#ef4444"
BORDER     = "#3f3f5c"


STYLE = f"""
QMainWindow, QWidget {{
    background-color: {DARK_BG};
    color: {TEXT};
    font-family: 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {PANEL_BG};
}}
QTabBar::tab {{
    background: {DARK_BG};
    color: {MUTED};
    padding: 10px 22px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: bold;
}}
QTabBar::tab:selected {{
    background: {ACCENT};
    color: white;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    font-weight: bold;
    color: {ACCENT2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}
QPushButton {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: bold;
}}
QPushButton:hover  {{ background-color: {ACCENT2}; }}
QPushButton:disabled {{ background-color: {BORDER}; color: {MUTED}; }}
QPushButton#secondary {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
    color: {TEXT};
}}
QPushButton#secondary:hover {{ background-color: {BORDER}; }}
QPushButton#danger {{
    background-color: {DANGER};
}}
QLineEdit, QComboBox, QSpinBox {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    color: {TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down  {{ border: none; }}
QComboBox::down-arrow {{ color: {TEXT}; }}
QTextEdit {{
    background-color: #12121e;
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: #a0ffb0;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    padding: 6px;
}}
QProgressBar {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 18px;
    text-align: center;
    color: white;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 6px;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {PANEL_BG};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QScrollArea {{ border: none; }}
QLabel#title {{
    font-size: 22px;
    font-weight: bold;
    color: {ACCENT2};
}}
QLabel#subtitle {{
    color: {MUTED};
    font-size: 12px;
}}
QFrame#divider {{
    background: {BORDER};
    max-height: 1px;
}}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ServerPackCreator – Beyond Packs")
        self.setMinimumSize(860, 680)
        self.worker = None
        self._manifest = None
        self._modpack_info = None

        self.setStyleSheet(STYLE)
        self._build_ui()
        self._load_modpacks()

    # ── UI Build ──────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # Header
        header = QHBoxLayout()
        title = QLabel("⚔  ServerPackCreator")
        title.setObjectName("title")
        sub = QLabel("by Catversal  •  Beyond Packs Edition")
        sub.setObjectName("subtitle")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(sub)
        root.addLayout(header)

        div = QFrame(); div.setObjectName("divider"); root.addWidget(div)

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._tab_create(),     "🔨  Create Pack")
        tabs.addTab(self._tab_properties(), "⚙  Server Properties")
        tabs.addTab(self._tab_update(),     "🔄  Update Config")
        root.addWidget(tabs)

        # Log
        log_box = QGroupBox("Log")
        log_lay = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(160)
        log_lay.addWidget(self.log_view)
        root.addWidget(log_box)

        # Progress
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)

    # ── Tab: Create ───────────────────────────────
    def _tab_create(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)

        # Client pack selector
        cp_box = QGroupBox("Client Pack Folder")
        cp_lay = QHBoxLayout(cp_box)
        self.cp_edit = QLineEdit()
        self.cp_edit.setPlaceholderText("Select the folder containing the modpack (config/, mods/, manifest.json)…")
        self.cp_edit.textChanged.connect(self._on_client_pack_changed)
        btn_browse = QPushButton("Browse…"); btn_browse.setObjectName("secondary")
        btn_browse.clicked.connect(self._browse_client_pack)
        cp_lay.addWidget(self.cp_edit)
        cp_lay.addWidget(btn_browse)
        lay.addWidget(cp_box)

        # Detected info
        info_box = QGroupBox("Detected Modpack")
        info_grid = QHBoxLayout(info_box)
        self.lbl_pack    = QLabel("–"); self.lbl_pack.setStyleSheet(f"color:{ACCENT2}; font-weight:bold;")
        self.lbl_version = QLabel("–"); self.lbl_version.setStyleSheet(f"color:{TEXT};")
        self.lbl_mc      = QLabel("–"); self.lbl_mc.setStyleSheet(f"color:{TEXT};")
        self.lbl_forge   = QLabel("–"); self.lbl_forge.setStyleSheet(f"color:{TEXT};")
        for label, caption in [
            (self.lbl_pack, "Pack"), (self.lbl_version, "Version"),
            (self.lbl_mc, "MC"), (self.lbl_forge, "Forge")
        ]:
            col = QVBoxLayout()
            cap = QLabel(caption); cap.setObjectName("subtitle")
            col.addWidget(cap); col.addWidget(label)
            info_grid.addLayout(col)
        lay.addWidget(info_box)

        # Options
        opt_box = QGroupBox("Options")
        opt_lay = QVBoxLayout(opt_box)

        row1 = QHBoxLayout()
        self.combo_hosting = QComboBox()
        self.combo_hosting.addItems(["Local (PC) – Install Forge", "Dedicated / Hosting – No Forge install"])
        row1.addWidget(QLabel("Hosting type:")); row1.addWidget(self.combo_hosting, 1)
        opt_lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_forge  = QCheckBox("Install Forge server automatically")
        self.chk_forge.setChecked(True)
        self.chk_jvm    = QCheckBox("Add recommended JVM arguments")
        self.chk_jvm.setChecked(True)
        self.chk_eula   = QCheckBox("Accept Minecraft EULA")
        row2.addWidget(self.chk_forge); row2.addWidget(self.chk_jvm); row2.addWidget(self.chk_eula)
        opt_lay.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("RAM allocation (GB):"))
        self.spin_ram = QSpinBox(); self.spin_ram.setRange(2, 64); self.spin_ram.setValue(8)
        row3.addWidget(self.spin_ram); row3.addStretch()
        opt_lay.addLayout(row3)
        lay.addWidget(opt_box)

        lay.addStretch()

        # Create button
        self.btn_create = QPushButton("🚀  Create Serverpack")
        self.btn_create.setFixedHeight(44)
        self.btn_create.clicked.connect(self._create_serverpack)
        lay.addWidget(self.btn_create)

        return w

    # ── Tab: Properties ───────────────────────────
    def _tab_properties(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner  = QWidget(); scroll.setWidget(inner)
        grid   = QVBoxLayout(inner)

        self._prop_fields = {}
        props = [
            ("gamemode",        "Gamemode",           ["survival", "creative", "adventure", "spectator"]),
            ("difficulty",      "Difficulty",         ["peaceful", "easy", "normal", "hard"]),
            ("max-players",     "Max Players",        None),
            ("view-distance",   "View Distance",      None),
            ("spawn-protection","Spawn Protection",   None),
            ("pvp",             "PvP",                ["true", "false"]),
            ("online-mode",     "Online Mode",        ["true", "false"]),
            ("allow-flight",    "Allow Flight",       ["true", "false"]),
            ("enable-command-block", "Command Blocks",["true", "false"]),
            ("white-list",      "Whitelist",          ["true", "false"]),
            ("enforce-whitelist","Enforce Whitelist", ["true", "false"]),
            ("motd",            "MOTD",               None),
            ("server-port",     "Server Port",        None),
            ("level-name",      "World Name",         None),
            ("level-seed",      "World Seed",         None),
        ]

        defaults = WorkerThread._default_server_props.__func__(None)

        for key, label, options in props:
            row = QHBoxLayout()
            lbl = QLabel(label); lbl.setFixedWidth(160)
            row.addWidget(lbl)
            if options:
                cb = QComboBox()
                cb.addItems(options)
                default_val = defaults.get(key, "")
                idx = options.index(default_val) if default_val in options else 0
                cb.setCurrentIndex(idx)
                self._prop_fields[key] = cb
                row.addWidget(cb, 1)
            else:
                le = QLineEdit(defaults.get(key, ""))
                self._prop_fields[key] = le
                row.addWidget(le, 1)
            grid.addLayout(row)

        grid.addStretch()
        lay.addWidget(scroll)
        return w

    # ── Tab: Update ───────────────────────────────
    def _tab_update(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(16)

        info = QLabel(
            "Clicking the button below downloads the latest config files\n"
            "(modpack_map.txt, remove lists) from GitHub and replaces your local copy."
        )
        info.setStyleSheet(f"color:{MUTED};")
        info.setWordWrap(True)
        lay.addWidget(info)

        self.btn_update = QPushButton("🔄  Download & Update Config from GitHub")
        self.btn_update.setFixedHeight(44)
        self.btn_update.clicked.connect(self._update_config)
        lay.addWidget(self.btn_update)
        lay.addStretch()
        return w

    # ── Slots ─────────────────────────────────────
    def _browse_client_pack(self):
        path = QFileDialog.getExistingDirectory(self, "Select Modpack Folder")
        if path:
            self.cp_edit.setText(path)

    def _on_client_pack_changed(self, path):
        if not os.path.isdir(path):
            return
        m = parse_manifest(path)
        if not m:
            self._manifest = None
            self.lbl_pack.setText("manifest.json not found")
            return
        self._manifest = m
        # Match against modpack map
        packs = load_modpack_map()
        self._modpack_info = None
        for p in packs:
            if p["match"].lower() in m["name"].lower() or p["name"].lower() == m["name"].lower():
                self._modpack_info = p
                break
        self.lbl_pack.setText(m["name"] if m["name"] else "Unknown")
        self.lbl_version.setText(m["version"])
        self.lbl_mc.setText(m["mc"])
        self.lbl_forge.setText(m["forge"])

    def _load_modpacks(self):
        packs = load_modpack_map()
        self._log(f"Loaded {len(packs)} modpack(s) from config.")

    def _get_server_props_overrides(self):
        overrides = {}
        for key, widget in self._prop_fields.items():
            if isinstance(widget, QComboBox):
                overrides[key] = widget.currentText()
            else:
                overrides[key] = widget.text()
        return overrides

    def _create_serverpack(self):
        cp = self.cp_edit.text().strip()
        if not cp or not os.path.isdir(cp):
            QMessageBox.warning(self, "Error", "Please select a valid client pack folder.")
            return
        if not self._manifest:
            QMessageBox.warning(self, "Error", "Could not read manifest.json from the selected folder.")
            return
        if not self._modpack_info:
            QMessageBox.warning(self, "Unknown Modpack",
                "This modpack was not found in modpack_map.txt.\n"
                "Update the config first, or add the pack manually.")
            return

        hosting = "local" if self.combo_hosting.currentIndex() == 0 else "dedicated"

        self._set_busy(True)
        self.worker = WorkerThread(
            "create_serverpack",
            client_pack    = cp,
            modpack_info   = self._modpack_info,
            manifest       = self._manifest,
            hosting_type   = hosting,
            install_forge  = self.chk_forge.isChecked(),
            server_props   = self._get_server_props_overrides(),
            ram_gb         = self.spin_ram.value(),
            jvm_args       = self.chk_jvm.isChecked(),
            accept_eula    = self.chk_eula.isChecked(),
        )
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _update_config(self):
        self._set_busy(True)
        self.worker = WorkerThread("update_config")
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, success, message):
        self._set_busy(False)
        if success:
            self._log(f"✅ Done: {message}")
            QMessageBox.information(self, "Success", message)
            self._load_modpacks()
        else:
            self._log(f"❌ Error: {message}")
            QMessageBox.critical(self, "Error", message)

    def _log(self, text):
        self.log_view.append(text)

    def _set_busy(self, busy):
        self.btn_create.setEnabled(not busy)
        self.btn_update.setEnabled(not busy)
        if not busy:
            self.progress.setValue(0)


# ─────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ServerPackCreator")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
