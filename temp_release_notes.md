### 📢 YAMA NOTLARI / PATCH NOTES (v2.0.3)

---

#### 🇹🇷 Türkçe

**Yenilikler ve İyileştirmeler**
- **Resmi Mojang OAuth Giriş Akışı:** WebEngine bileşeni kaldırılarak işletim sisteminin varsayılan web tarayıcısı üzerinden çalışan resmi ve sade giriş ekranına geçildi (`00000000402b5328`).
- **Otomatik Pano Dinleyici (Clipboard Listener):** Microsoft girişi sonrası yönlendirme linki kopyalandığı anda launcher kodu arka planda otomatik algılar ve tıklama gerektirmeden oturumu açar.
- **Çevrimdışı (Offline) Hesap Desteği:** Sekmeli giriş arayüzü ile Mojang standardında deterministik UUID (`uuid.uuid3`) üreten çevrimdışı hesap oluşturma desteği eklendi.
- **Gerçek Zamanlı Karakter Kafası Önizlemesi:** Çevrimdışı modda kullanıcı adı yazılırken Minotar servisi üzerinden oyuncu avatarı gerçek zamanlı önizlenir.
- **Hızlı Başlatma (Instant Launch):** Çevrimdışı hesaplar gereksiz ağ doğrulama gecikmelerini atlayarak oyunu anında başlatır.
- **Arayüz Göstergeleri:** Hesap durum çubuğunda açık mavi `(Çevrimdışı)` veya yeşil `(Microsoft)` rozeti gösterilir.
- **Güvenlik & Bütünlük:** SHA-256 kurulum paketi doğrulayıcı, crash loglarında kişisel token maskeleme ve arayüz donma önlemleri uygulandı.

**Hata Düzeltmeleri**
- Derleme çıktılarında PyInstaller WebEngine uyumsuzlukları giderildi.
- Token yenileme ve doğrulama iş parçacıklarının senkronizasyon hataları düzeltildi.

*Karşılaştığınız diğer sorunları GitHub Issues üzerinden iletmeyi unutmayın.*

---

#### 🇬🇧 English

**Improvements**
- **Official Mojang OAuth Login Flow:** Removed WebEngine dependency in favor of external system browser authentication using the official Minecraft Client ID (`00000000402b5328`).
- **Automatic Clipboard Listener:** Instantly detects copied Microsoft redirect authentication codes from the clipboard and signs in seamlessly without manual clicks.
- **Offline Account Support:** Added tabbed login UI with standard deterministic Mojang offline UUID generation (`uuid.uuid3`), preserving world saves and player inventories across sessions.
- **Real-Time Avatar Preview:** Dynamic Minotar skin head preview updates as the offline username is typed.
- **Instant Launch for Offline Accounts:** Bypasses token validation network delays, launching Minecraft immediately.
- **Account Badges:** Distinctive cyan `(Offline)` and green `(Microsoft)` account status indicators.
- **Security & Integrity:** SHA-256 installer hash verification, crash log token sanitization, and UI freeze mitigations.

**Bug Fixes**
- Resolved PyInstaller WebEngine exclusion and binary packaging conflicts.
- Fixed thread synchronization edge cases during token refresh and session validation.

*If you run into any issues, please submit a report on GitHub Issues.*

---

**Doğrulama Özeti / Verification Checksum:**
- `SHA256: ffd803103c89ea9d23be68cee330ea4f85fa88e8d146262683fe28acfceb2171`
