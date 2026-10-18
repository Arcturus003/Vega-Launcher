<div align="center">

# 🌌 Vega Launcher

**Next-Generation Minecraft Client with Electric Amethyst Aesthetics, Procedural Audio, and Zero-Friction Runtime Provisioning**

[![Latest Release](https://img.shields.io/github/v/release/Arcturus003/Vega-Launcher?color=8B5CF6&label=S%C3%BCr%C3%BCm%20%2F%20Release&style=for-the-badge&logo=github)](https://github.com/Arcturus003/Vega-Launcher/releases/latest)
[![Total Downloads](https://img.shields.io/github/downloads/Arcturus003/Vega-Launcher/total?color=06B6D4&label=%C4%B0ndirmeler%20%2F%20Downloads&style=for-the-badge&logo=windows)](https://github.com/Arcturus003/Vega-Launcher/releases)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Arcturus003/Vega-Launcher/releases)
[![Visitors](https://visitor-badge.laobi.icu/badge?page_id=Arcturus003.Vega-Launcher&left_color=12121A&right_color=8B5CF6)](https://github.com/Arcturus003/Vega-Launcher)

<p align="center">
  <a href="#-türkçe"><b>🇹🇷 Türkçe</b></a> •
  <a href="#-english"><b>🇬🇧 English</b></a>
</p>

![Vega Launcher Splash Banner](assets/splash.jpg)

</div>

---

<a name="-türkçe"></a>
## 🇹🇷 Türkçe

**Vega Launcher**, oyunculara ve mod yapımcılarına modern, akıcı ve yüksek performanslı bir Minecraft deneyimi sunmak için Python ve PySide6 (Qt6) ile sıfırdan geliştirilmiş yeni nesil bir masaüstü başlatıcıdır.

### 🌟 Öne Çıkan Özellikler (v2.0.0)

| Özellik | Açıklama |
| :--- | :--- |
| 🔮 **Enderman & Obsidyen Estetiği** | Özel piksel çizim simgeler, koyu ametist arayüz (`#12121A`), neon vurgular ve dinamik vitrin kartları. |
| 🎵 **Prosedürel Minecraft Ses Motoru** | WAV dosyası bağımlılığı olmadan gerçek zamanlı matematiksel frekans senteziyle üretilen buton, şalter, açılış ve seviye atlama sesleri. |
| ✨ **Akıllı Parçacık Sistemi** | Arayüzde süzülen void ve ametist parçacıkları; oyun açıldığında veya pencere simge durumuna küçültüldüğünde **%0 CPU/GPU** kullanan akıllı uyku modu. |
| 🎨 **5 Dinamik Vurgu Teması** | Tek tıkla değiştirilebilen temalar: *Elektrik Ametist*, *Ender İncisi*, *Nether Kızılı*, *Zümrüt Yeşili* ve *Derin Karanlık*. |
| ☕ **Sıfır Kurulum Java Sağlayıcı** | Temiz bir bilgisayarda veya sanal makinelerde dahi Java kurulumuna gerek kalmadan Mojang'ın resmi mini-JRE'sini otomatik indirir ve ayarlar. |
| 📦 **Vega Modpack Yükleyici** | Modrinth kataloğundan tek tıkla arama, sürüm ve yükleyici (Fabric, Quilt, Forge, NeoForge) seçimi, RAM ön ayarları ve yerel `.mrpack`/`.zip` desteği. |
| 🛡️ **Premium Güvenlik & DPAPI** | Microsoft OAuth kimlik doğrulaması ve Windows DPAPI ile diskte şifrelenmiş oturum jetonları. |
| ⚡ **Derin Mimari Hatları** | `GameLaunchPipeline`, `ServerProcessCoordinator` ve `AuthenticationVault` sayesinde sıfır arayüz donması ve güvenli yedekleme. |

---

### 🚀 Kurulum ve İndirme

1. **[En Son Kurulum Paketini İndirin (v2.0.0)](https://github.com/Arcturus003/Vega-Launcher/releases/latest)**  
   *(Dosya: `VegaLauncher_Setup_v2.0.0.exe`)*
2. Kurulum sihirbazını başlatın ve yönergeleri izleyin:

<div align="center">
  <img src="assets/screenshots/installer_welcome.png" width="650" alt="Vega Launcher Kurulum Ekranı" />
</div>

3. Masaüstündeki **Vega Launcher** kısayoluna çift tıklayın, Microsoft hesabınızla giriş yapın ve oynamaya başlayın!

---

### 🛠️ Geliştiriciler İçin (Kaynak Koddan Çalıştırma)

Projeyi kaynak koddan yerel olarak derlemek veya katkıda bulunmak için:

```powershell
# 1. Depoyu klonlayın
git clone https://github.com/Arcturus003/Vega-Launcher.git
cd Vega-Launcher

# 2. Python sanal ortamını oluşturun ve etkinleştirin
python -m venv venv
.\venv\Scripts\activate

# 3. Bağımlılıkları yükleyin
pip install -r requirements.txt

# 4. Bütünlük kontrolünü doğrulayın
python integrity_check.py verify

# 5. Vega Launcher'ı başlatın
python main.py
```

*Tek başına Windows kurulum paketi üretmek için: Inno Setup 6 ile `setup.iss` derlenir.*

---

<a name="-english"></a>
## 🇬🇧 English

**Vega Launcher** is an advanced, high-performance Minecraft desktop client built from the ground up using Python and PySide6 (Qt6), designed to provide a cohesive, visually striking, and seamless launcher experience.

### 🌟 Key Features (v2.0.0)

| Feature | Highlight |
| :--- | :--- |
| 🔮 **Enderman Obsidian Aesthetic** | Bespoke pixel art icons, deep obsidian surfaces (`#12121A`), amethyst neon glow, and dynamic hero banners. |
| 🎵 **Procedural Audio Engine** | Pure real-time frequency-synthesized Minecraft sound effects (clicks, levers, launches, level-ups) with zero external audio assets. |
| ✨ **Smart Particle System** | Ambient floating void sparks with an automated intelligent performance mode that drops to **0% CPU/GPU** during gameplay or minimization. |
| 🎨 **5 Dynamic Accent Themes** | Instant theme switcher featuring *Electric Amethyst*, *Ender Pearl*, *Nether Crimson*, *Emerald Lush*, and *Deep Dark*. |
| ☕ **Zero-Friction Java Provisioning** | Automatically resolves system runtimes or downloads Mojang's official minimal JRE on clean PCs or sandboxes—no manual Java setup required. |
| 📦 **Vega Modpack Installer** | Browse Modrinth, pick loaders (Fabric, Quilt, Forge, NeoForge), select versions, adjust RAM presets, and install local `.mrpack`/`.zip` archives. |
| 🛡️ **Microsoft OAuth & DPAPI** | Genuine Microsoft account integration with Windows DPAPI at-rest token protection. |
| ⚡ **Decoupled Deep Modules** | Backed by `GameLaunchPipeline`, `ServerProcessCoordinator`, and `AuthenticationVault` for non-blocking UI responsiveness. |

---

### 🚀 Getting Started

1. Download **[VegaLauncher_Setup_v2.0.0.exe](https://github.com/Arcturus003/Vega-Launcher/releases/latest)** from the official Releases page.
2. Complete the setup wizard.
3. Launch Vega Launcher, authenticate with your Microsoft account, and jump straight into Minecraft!

---

### 🛠️ Building from Source

```powershell
git clone https://github.com/Arcturus003/Vega-Launcher.git
cd Vega-Launcher
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python integrity_check.py verify
python main.py
```

---

<div align="center">

### 🌍 Global Visitors / Ziyaretçiler

[![Visitors Flag Counter](https://api.visitorbadge.io/api/visitors?path=Arcturus003%2FVega-Launcher&label=TOTAL%20VISITORS&labelColor=%2312121a&countColor=%238b5cf6&style=flat-square)](https://github.com/Arcturus003/Vega-Launcher)

<br/>

**Vega Launcher** is open-source software crafted with passion.  
Minecraft is a trademark of Mojang Synergies AB. Vega Launcher is not affiliated with Mojang or Microsoft.

</div>
