### 📢 YAMA NOTLARI / PATCH NOTES

---

#### 🇹🇷 Türkçe

**Yenilikler ve İyileştirmeler**
- **Akıllı Motor Kurucu Doğrulaması:** 1.20.1 ve altı sürümler için NeoForge seçimi engellendi; uyumsuzluk durumunda kullanıcıyı otomatik olarak Forge/Fabric'e yönlendiren bilgilendirici sistem devreye alındı.

**Hata Düzeltmeleri**
- NeoForge profillerinde sürüm numarasının `1.265` olarak algılanıp Modlar ve Shaderlar sayfalarının "Sonuç bulunamadı." hatası vermesine yol açan regex hatası giderildi.
- `clear_grid()` metodunun arama epoch sayacını yanlışlıkla artırıp kart listelemede yarış durumuna yol açması engellendi.
- `main.py` içindeki mükerrer motor sürüm tespit kodları ve `auth_window.py` içindeki ölü fonksiyonlar temizlendi.

*Karşılaştığınız diğer sorunları GitHub Issues üzerinden iletmeyi unutmayın.*

---

#### 🇬🇧 English

**Improvements**
- **Preemptive Engine Compatibility Guard:** Prevented unsupported loader installations (e.g. NeoForge on MC 1.20.1) and added friendly auto-selection fallback to Forge/Fabric.

**Bug Fixes**
- Fixed an issue where NeoForge version strings were incorrectly parsed as `1.265`, causing Mod and Shader browser tabs to display "No results found".
- Fixed search epoch counter inflation inside `clear_grid()` that triggered stale card race conditions.
- Removed dead authentication helpers and duplicate loader version inspection code.

*If you run into any issues, please submit a report on GitHub Issues.*
