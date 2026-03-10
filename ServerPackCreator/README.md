# ⚔ ServerPackCreator – Beyond Packs

A cross-platform GUI tool to convert a downloaded Minecraft modpack (CurseForge)
into a ready-to-run dedicated server pack.

> Built with Python + PyQt6 • Works on Windows & Linux • No Python installation needed

---

## ✨ Features

- 📁 **Folder browser** – pick your client pack with one click
- 🔍 **Auto-detect** – reads `manifest.json` to identify pack, MC version & Forge version
- 📋 **Smart copy** – copies `config`, `mods`, `kubejs`, `defaultconfigs` (+ `tacz` if needed)
- 🗑 **Client-mod removal** – automatically removes client-only mods using remove lists
- 🔨 **Forge auto-install** – downloads & runs the Forge installer for you
- ⚙ **Server.properties editor** – configure gamemode, difficulty, MOTD, ports and more
- 🔄 **Config auto-update** – pulls the latest config files from GitHub with one click
- 📊 **Progress bar + live log** – watch every step in real time

---

## 🚀 Usage (end users)

1. Download the latest release for your OS from the **Releases** tab
2. Extract the zip / tar.gz
3. Run `ServerPackCreator.exe` (Windows) or `./ServerPackCreator` (Linux)
4. Paste your CurseForge modpack folder into the tool and follow the steps

> **Java 17–21 required** for Forge server installation.
> Download from https://adoptium.net/de/temurin/releases

---

## 🛠 Development setup

```bash
# Clone
git clone https://github.com/Catversal/beyond-forge-server-creator.git
cd beyond-forge-server-creator/ServerPackCreator

# Install dependencies
pip install -r requirements.txt

# Run from source
python src/main.py
```

---

## 📦 Building standalone executables

```bash
pip install pyinstaller PyQt6
pyinstaller ServerPackCreator.spec --clean
```

Output will be in `dist/ServerPackCreator/`.

### Automated builds via GitHub Actions

Push a version tag to trigger an automatic build for Windows & Linux:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions will:
1. Build `ServerPackCreator.exe` on Windows
2. Build `ServerPackCreator` binary on Linux
3. Create a GitHub Release with both files attached

---

## 📂 Project structure

```
ServerPackCreator/
├── src/
│   └── main.py                  # Main application
├── config/
│   ├── modpack_map.txt           # Supported modpacks
│   └── remove_list/             # Client-only mod lists per pack
├── requirements.txt
├── ServerPackCreator.spec        # PyInstaller build config
└── .github/
    └── workflows/
        └── build.yml             # Auto-build & release
```

---

## 🗺 Adding new modpacks

Edit `config/modpack_map.txt`:

```
ID|Display Name|Match String|MC Version|Copy TACZ (0/1)
5|My New Pack|My New Pack|1.21.1|0
```

Add a remove list at `config/remove_list/my_new_pack_remove.txt` with one mod prefix per line.

---

## 📜 License

MIT – see [LICENSE](../LICENSE)
