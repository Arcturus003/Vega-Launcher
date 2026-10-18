# Vega Launcher

A fast, clean Minecraft launcher with built-in Modrinth support, automatic Java setup, and instance isolation.

[![Release](https://img.shields.io/github/v/release/Arcturus003/Vega-Launcher?style=flat&color=8B5CF6)](https://github.com/Arcturus003/Vega-Launcher/releases/latest)
[![Build & Tests](https://github.com/Arcturus003/Vega-Launcher/actions/workflows/test.yml/badge.svg)](https://github.com/Arcturus003/Vega-Launcher/actions)
[![Downloads](https://img.shields.io/github/downloads/Arcturus003/Vega-Launcher/total?style=flat&color=64748B)](https://github.com/Arcturus003/Vega-Launcher/releases)

English • [Türkçe](README_TR.md)

![Vega Launcher Preview](assets/social_preview.png)

## Features

- **Built-in Modrinth Browser**: Search and install modpacks, mods, and shaders directly inside the client.
- **Automatic Java Setup**: Detects version requirements and downloads the official Mojang JRE automatically when needed.
- **Mod Loader Support**: Full support for Fabric, Quilt, Forge, and NeoForge.
- **Local Modpack Import**: Install `.mrpack` and `.zip` archives directly from your computer.
- **Isolated Profiles**: Keeps saves, mods, and configurations separated per instance.
- **Secure Logins**: Microsoft OAuth authentication with session tokens encrypted locally via Windows DPAPI.
- **Customizable Aesthetics**: Obsidian dark surfaces with selectable accent colors and procedural sound effects.

## Installation

Download the latest installer from the [Releases](https://github.com/Arcturus003/Vega-Launcher/releases/latest) page:

👉 **[Download VegaLauncher_Setup_v2.0.0.exe](https://github.com/Arcturus003/Vega-Launcher/releases/latest)**

Run the setup wizard, sign in with your Microsoft account, and launch the game.

## Building from Source

Requirements: Python 3.12+ on Windows.

```powershell
# Clone the repository
git clone https://github.com/Arcturus003/Vega-Launcher.git
cd Vega-Launcher

# Set up virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run
python integrity_check.py verify
python main.py
```

Run tests:
```powershell
python tests/run_tests.py
```

## License

All Rights Reserved.
