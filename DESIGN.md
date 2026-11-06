# Vega Launcher — Design System & Visual Authority

<!-- impeccable:design-schema 1 -->

## Platform

desktop (PySide6 / Qt 6 + QSS)

## Theme & Aesthetic

**Obsidian Void & Cyber-Ender**: Derin obsidyen arka planlar, The End boyutu atmosferi, süzülen mor parçacıklar, telepatik siyan/zümrüt vurgular ve yüksek prodüksiyonlu AAA oyun istemcisi hissi (Steam/Battle.net standardı).

---

## Design Tokens

### 1. Color Palette

| Token | Hex | Role |
|---|---|---|
| `--bg-void` | `#08090f` | Ana pencere derin uzay/obsidyen tabanı |
| `--surface-base` | `#0d0e18` | Sol kenar çubuğu ve alt kontrol çubuğu arka planı |
| `--surface-card` | `#111322` | Modpack, profil ve sunucu kartları |
| `--surface-card-hover` | `#16192c` | Kart hover durumu |
| `--surface-modal` | `#0e101c` | Sağ detay çekmecesi ve diyalog pencereleri |
| `--border-subtle` | `rgba(139, 92, 246, 0.15)` | Standart 1px kart ve panel sınırları |
| `--border-glow` | `rgba(168, 85, 247, 0.55)` | Kart ve odaklanılan alanların Ender parıltısı |
| `--accent-ender` | `#9333ea` / `#a855f7` | Birincil aksiyonlar, 'OYNA' butonu, aktif sekmeler |
| `--accent-eye` | `#06b6d4` / `#10b981` | Ender Gözü zümrüt/siyan (Çevrimiçi durum, NeoForge rozeti) |
| `--text-primary` | `#f1f5f9` | Ana başlıklar, kart isimleri, vurgulu metinler |
| `--text-secondary` | `#94a3b8` | Açıklama metinleri, yazar bilgileri, meta veriler |
| `--text-muted` | `#64748b` | İkincil etiketler, telif ve sürüm dipnotları |

### 2. Typography

- **Gövde & Arayüz:** Plus Jakarta Sans / Segoe UI (Temiz, modern, yüksek okunabilirlik).
- **Teknik & Kod:** JetBrains Mono / Consolas (Sürümler, RAM miktarı, portlar, log konsolu).
- **Minecraft Nostalji:** MinecraftFive-Bold / Minecraft.ttf (Yalnızca öne çıkan banner rozetleri ve başlık vurguları; mikro metinlerde kesinlikle kullanılmaz).
- **Minimum Boyut:** 12px taban yazı boyutu; 11px yalnızca monospaced rozetlerde kullanılabilir.

### 3. Spacing & Radius Scale

- **Radius:** Kartlar `12px` - `16px`, butonlar `10px` - `12px`, rozetler `6px` - `8px`.
- **Spacing:** Standart ızgara boşlukları `16px`, iç padding `16px` - `20px`.

### 4. Motion & Micro-interactions

- **Hover Geçişleri:** `150ms - 200ms` süreli yumuşak mor sınır ışıltısı (`rgba(168, 85, 247, 0.55)`).
- **Çekmece Hareketi:** Sağ detay paneli akıcı açılış (slide-in / expand).
- **Parçacık Efekti:** Arka planda CPU tüketmeyen hafif ve yavaşça yükselen mor ve siyan Ender parçacıkları.

### 5. Audio Architecture (Minecraft Authentic FX)

- **UI Click:** Kısa, tok Minecraft ahşap düğme sesi (800Hz -> 120Hz düşüş).
- **Drawer / Select:** Enderman ışınlanma / portaldan geçiş fısıltısı (testereli dalga frekans eğrisi).
- **Success / Level Up:** Deneyim küresi (XP) toplama / seviye atlama tınısı (4 kademeli sinüs arpeji).
- **Denetim:** Tüm sesler Ayarlar ekranından tek tıkla tamamen kapatılabilir.

---

## Layout Hierarchy

1. **Pencere Başlığı (Custom Header):** 40px yükseklik; logo, sürüm bilgisi, sunucu API çevrimiçi durumu, Minecraft FX ses aç/kapa butonu ve pencere kontrolleri.
2. **Sol Kenar Çubuğu (Sidebar):** 240px genişlik; kullanıcı kartı, Kütüphane menüsü (Profillerim, Mod Paketleri, Bireysel Modlar, Shaderlar), Sunucu menüsü ve Ayarlar.
3. **Hero Vitrin Bannerı:** İçerik alanının üstünde; haftanın/en popüler mod paketini tanıtan geniş, sinematik Ender afişi.
4. **Kart Izgarası (Content Grid):** 3 sütunlu modüler kartlar; kapak ikonu, başlık, yazar, indirme sayısı, loader rozetleri ve hover olunca beliren hızlı detay butonu.
5. **Sağ Detay Çekmecesi (Slide-in Drawer):** 380px genişlik; seçilen paketin tam açıklaması, ekran görüntüleri, RAM seçici (4GB / 6GB / 8GB) ve 'Modpack'i Kur ve Profil Oluştur' butonu.
6. **Entegre Komuta Çubuğu (Launch Dock):** 76px yükseklik; sol tarafta seçili profil özeti, ortada çok katmanlı akıllı indirme ve başlatma durum çubuğu, sağda devasa parıldayan Ender gradyanlı 'OYNA' butonu.
