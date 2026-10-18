<div align="center">

# Vega Launcher

**A fast, obsidian-themed Minecraft launcher with built-in Modrinth browsing and automated Java provisioning.**

[![Release](https://img.shields.io/github/v/release/Arcturus003/Vega-Launcher?style=flat&color=8B5CF6)](https://github.com/Arcturus003/Vega-Launcher/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Arcturus003/Vega-Launcher/total?style=flat&color=64748B)](https://github.com/Arcturus003/Vega-Launcher/releases)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0F172A?style=flat)](https://github.com/Arcturus003/Vega-Launcher/releases)
[![Python](https://img.shields.io/badge/Python-3.14%20%7C%20PySide6-1E293B?style=flat)](https://www.python.org/)

<br/>

<a href="https://github.com/Arcturus003/Vega-Launcher/releases/latest">
  <img src="https://img.shields.io/badge/Download-VegaLauncher__Setup__v2.0.0.exe-8B5CF6?style=for-the-badge&logo=windows&logoColor=white" height="38" alt="Download Vega Launcher" />
</a>

<br/><br/>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#-türkçe-özet">Türkçe Özet</a> •
  <a href="#development">Development</a>
</p>

![Vega Launcher Banner](assets/splash.jpg)

</div>

---

## Features

### Zero-Friction Java Setup
Running on a clean PC or fresh Windows install? Vega Launcher detects the required Java version for your loader (Java 8 for 1.16, Java 17 for 1.18–1.20.4, Java 21 for 1.20.5+) and pulls Mojang's official mini-JRE runtime on demand. No manual JDK downloads, no PATH configuration.

### Modrinth Browser & Modpack Installer
Search, filter, and install modpacks, mods, and shaders directly inside the client.
- Supports **Fabric**, **Quilt**, **Forge**, and **NeoForge**.
- 1-click RAM presets (4 GB, 6 GB, 8 GB).
- Local `.mrpack` and `.zip` archive installation.
- Transactional update rollback: existing mods are safely backed up before any update.

### Obsidian & Void Aesthetics
Built with PySide6 (Qt6) and custom styling inspired by dark obsidian surfaces:
- **5 Accent Themes**: Electric Amethyst, Ender Pearl, Nether Crimson, Emerald Lush, and Deep Dark.
- **Smart Particles**: Ambient void particles that completely idle (0% CPU/GPU) when a game is running or the window is minimized.
- **Procedural Sound Effects**: Synthesized click, lever, launch, and level-up audio with no bloated audio dependencies.
- Custom profile showcase banners (custom image or atmospheric gradients).

### Performance & Security
- **Independent Profiles**: Separate instance folders, isolated game saves, and dedicated configs.
- **Encrypted Credentials**: Microsoft OAuth tokens are encrypted at-rest using Windows DPAPI (`CryptProtectData`), never saved in plaintext.
- **Decoupled Architecture**: Launch pipeline (`GameLaunchPipeline`) and server lifecycle (`ServerProcessCoordinator`) run off the GUI thread—no UI freezes during launch or world saves.

---

## Quick Start

1. Download [`VegaLauncher_Setup_v2.0.0.exe`](https://github.com/Arcturus003/Vega-Launcher/releases/latest).
2. Run the installer and launch Vega Launcher.
3. Sign in with your Microsoft account, select a profile or browse Modrinth, and click **Oyna**.

<div align="center">
  <img src="assets/screenshots/installer_welcome.png" width="600" alt="Installer Setup Screen" />
</div>

---

<a name="-türkçe-özet"></a>
## 🇹🇷 Türkçe Özet

Vega Launcher; oyuncuların Java kurma derdiyle uğraşmadığı, doğrudan Modrinth kütüphanesinden modpack ve mod indirebildiği, koyu ametist/obsidyen temalı masaüstü Minecraft istemcisidir.

### Neden Vega?
* **Otomatik Java Sağlama**: Temiz Windows veya Sandbox kurulumlarında bile sistemde Java aramaya gerek kalmaz; Mojang'ın resmi hafif JRE paketini otomatik çeker ve oyunu açar.
* **Dahili Modrinth Tarayıcısı**: Fabric, Quilt, Forge veya NeoForge fark etmeksizin tek tıkla mod ve modpack kurun; yerel `.mrpack` arşivlerini doğrudan içeri aktarın.
* **Akıllı Performans Modu**: Arka planda süzülen parçacıklar oyun başladığında veya pencere simge durumuna küçüldüğünde %0 işlemci kullanır.
* **Güvenli Oturum**: Microsoft OAuth oturumları Windows DPAPI ile yerel olarak şifrelenir.
* **Kişiselleştirme**: 5 farklı Minecraft renk teması, profil vitrin kartları ve prosedürel ses efektleri.

---

## Development

```powershell
# Clone the repository
git clone https://github.com/Arcturus003/Vega-Launcher.git
cd Vega-Launcher

# Setup virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Verify source integrity & run
python integrity_check.py verify
python main.py
```

To run the test suite:
```powershell
python -m unittest discover tests
```

---

<div align="center">

Vega Launcher is an independent open-source project and is not affiliated with Mojang Studios or Microsoft.

</div>
