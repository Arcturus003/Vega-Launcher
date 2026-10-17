### 📢 YAMA NOTLARI / PATCH NOTES

---

#### 🇹🇷 Türkçe

**Yenilikler ve İyileştirmeler**
- **Ender Pearl & Enderman Teması:** Vega Launcher için özel Enderman uygulama ikonu, masaüstü kısayolları için Ender Pearl ikonu, mor elektrik ametist detayları ve obsidian yüzey tasarımı eklendi.
- **Prosedürel Minecraft Ses Motoru:** Tıklamalar, şalter geçişleri, oyun açılışları ve bildirimler için saf frekans sentezli prosedürel ses efektleri eklendi. Ayarlar sekmesinden ses seviyesi ayarlanabilir ve kapatılabilir.
- **Ortam Parçacık Sistemi (Akıllı Mod):** Arayüzde süzülen ametist ve void parçacıkları eklendi. Oyun açıldığında veya pencere küçültüldüğünde GPU/CPU kullanımını %0'a indiren akıllı performans modu entegre edildi.
- **Dinamik Minecraft Vurgu Temaları:** Ayarlar menüsünden tek tıkla geçiş yapılabilen 5 renk teması (Elektrik Ametist, Ender İncisi, Nether Kızılı, Zümrüt Yeşili, Derin Karanlık) eklendi.
- **Profil Vitrin Arka Planı (Hero Banner):** Profil düzenleme penceresinden ana ekrandaki profil vitrin kartına özel arka plan resmi veya hazır atmosfer gradyanı atama desteği eklendi.
- **Sunucu Süreç Koordinatörü (`ServerProcessCoordinator`):** Sunucu başlatma ve kapatma süreçleri arayüzden ayrıldı; sunucunun kapanmayıp asılı kalması sorunu otomatik watchdog zamanlayıcısıyla çözüldü.
- **İstemci Başlatma Hattı (`GameLaunchPipeline`):** İstemci hazırlık adımları ayrıştırılarak profiller arası geçiş yaparken ve oyunu başlatırken yaşanan arayüz donması ortadan kaldırıldı.
- **Hızlı Kimlik Doğrulama Kasası (`AuthenticationVault`):** Kimlik doğrulama kontrolleri asenkron soket altyapısıyla hızlandırıldı.

**Hata Düzeltmeleri**
- **Masaüstü Kısayolu Hatası Düzeltildi:** Windows Script Host (Kod: 800A0408) derleme hatası giderildi; doğrudan yerel Windows COM ve PowerShell motoruna geçilerek masaüstü kısayollarının sorunsuz oluşturulması sağlandı.
- **Sunucu Kapanışında Asılı Kalma Çözüldü:** Sunucunun durdurulurken arka planda kilitlenmesi ve kapanması için zorla kapatma gerektirmesi sorunu giderildi.
- **Zorla Kapatma Güvenlik Kilidi:** Sunucu kapanırken diske yazılan dünyaların bozulmaması için kazara erken tıklamalara karşı 3 saniyelik güvenlik koruması eklendi.
- **Dungeons Çoklu Sürücü Taraması:** Dungeons kurulu olmayan bilgisayarlarda boş klasör ağacı açılması engellendi; kurulu sistemlerde ise A'dan Z'ye tüm sürücüler, Steam ve Xbox Games otomatik olarak taranır hale getirildi.
- **PySide6 Slot Hataları:** Menü aksiyonlarındaki tıklama olaylarının `TypeError` vermesi önlendi (`checked=False`).

*Karşılaştığınız diğer sorunları GitHub Issues üzerinden iletmeyi unutmayın.*

---

#### 🇬🇧 English

**Improvements**
- **Ender Pearl & Enderman Theme:** Custom Enderman application icon, Ender Pearl desktop shortcut icon, electric amethyst accents, and obsidian dark surfaces.
- **Procedural Minecraft Sound Engine:** Real-time frequency-synthesized audio effects for clicks, lever toggles, launches, and alerts. Configurable via Settings with volume control and toggle.
- **Ambient Particle System (Smart Performance Mode):** Floating amethyst and void particles with automated 0% CPU/GPU throttle when game is running or window is minimized.
- **Dynamic Accent Themes:** One-click theme switching between 5 palettes (Electric Amethyst, Ender Pearl, Nether Crimson, Emerald Lush, Deep Dark).
- **Profile Showcase Banner (Hero Banner):** Added support for setting custom background images or atmospheric preset gradients for the main home hero card in the profile editor.
- **Server Process Coordinator (`ServerProcessCoordinator`):** Decoupled server lifecycle and shutdown watchdog from the UI, resolving server hangs on exit.
- **Game Launch Pipeline (`GameLaunchPipeline`):** Decoupled launch preparation and validation, eliminating UI freezing when switching profiles or launching.
- **Fast Authentication Vault (`AuthenticationVault`):** Accelerated login state verification via non-blocking offline socket checks.

**Bug Fixes**
- **Desktop Shortcut Error Resolved:** Fixed Windows Script Host compilation error (Code: 800A0408) by migrating to native Windows COM and PowerShell automation.
- **Server Shutdown Hang Resolved:** Fixed server remaining stuck in the background on exit and requiring force-kill.
- **Early Force-Kill Safety Shield:** Added a 3-second safety cooldown before enabling force termination to prevent world save corruption.
- **Multi-Drive Dungeons Discovery:** Prevented dummy directory creation when Dungeons is absent; enabled dynamic multi-drive scanning (A-Z, Steam, Xbox Games) when installed.
- **PySide6 Slot Fix:** Hardened action click lambdas against `TypeError` exceptions (`checked=False`).

*If you run into any issues, please submit a report on GitHub Issues.*
