# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

## Stack

Python 3.12+, PySide6 (Qt 6), Custom QSS Theming, minecraft_launcher_lib, CurseForge API, Mojang Auth / Xbox Live.

## Users

Birincil kullanıcılar, modlu Minecraft oynayan (özellikle Create, Cobblemon, korku/RPG paketleri) ve kendi arkadaş gruplarıyla yerel/uzak sunucu kurup oynamak isteyen oyuncular ile performans/optimizasyon arayan oyunculardır.

## Product Purpose

Vega Launcher, oyuncuların teknik Java yapılandırmaları, çakışan kütüphane sürümleri veya karmaşık sunucu dosyalarıyla uğraşmadan; tek tıkla mod paketlerini kurmalarını, profillerini izole yönetmelerini ve yerel sunucularını anında ayağa kaldırmalarını sağlayan modern, yüksek performanslı ve güvenli bir Minecraft istemcisidir.

## Positioning

Sıradan başlatıcıların hantal ve donuk arayüzlerinden farklı olarak; derin End/Enderman görsel atmosferi, sıfır gecikmeli akıcı animasyonları, entegre tek tık sunucu motoru (Purpur/Paper/Forge) ve doğrudan Minecraft evreninden ilham alan sesli geri bildirimleriyle oyuncuya premium bir AAA istemci hissi yaşatır.

## Operating Context

- Windows 10/11 masaüstü ortamı.
- Çift ekran kartlı (NVIDIA Optimus / AMD Switchable) oyuncu laptopları ve masaüstü bilgisayarlar.
- Yüksek bellek (RAM) ve disk I/O tüketimi gerektiren devasa mod paketlerinin (100+ mod) indirilmesi, kurulması ve arka plan izlenmesi.
- Java 8, 17, 21 otomatik kurulumları ve yerel ağ (LAN / port yönlendirme) sunucu süreçleri.

## Capabilities and Constraints

- **Yetenekler:** Vanilla, Fabric, Quilt, Forge, NeoForge (1.21+) otomatik provizyonu; CurseForge modpack & mod arama ve tek tıkla kurulum; otomatik Java tespiti ve indirme; yerel sunucu yönetimi ve canlı konsol; dahili çökme analizi ve yedekleme sistemi.
- **Kısıtlamalar:** PySide6 thread güvenliği (UI güncellemeleri yalnızca Signal/Slot mekanizmasıyla yapılmalıdır); Inno Setup dağıtımı; Windows UAC izin sınırları (`runas` fallback).

## Brand Commitments

- **İsim & Kimlik:** Vega Launcher — Arcturus.
- **Ana Motif:** The End & Enderman (Derin obsidyen yüzeyler, süzülen mor parçacıklar, telepatik siyan/zümrüt Ender Gözü ışıltıları, Minecraft sesleri).
- **Dil:** Türkçe ve İngilizce çift dil desteği.

## Product Principles

1. **Oyuncuyu Bekletme (Zero-Friction Launch):** Oyun başlatma tek tıkla tamamlanmalı; Java, kütüphaneler ve modlar arka planda sessizce ve kesintisiz halledilmelidir.
2. **Kusursuz Görsel Bütünlük (Impeccable Obsidian Surface):** Her kart, buton, sekme ve giriş kutusu aynı obsidyen tasarım kurallarına uymalı; hiçbir ekran jenerik veya yamalı görünmemelidir.
3. **Şeffaf ve Net Durum İletişimi:** İndirme, çökme veya yetki hataları teknik jargon yerine kullanıcıya çözümüyle birlikte net olarak bildirilmelidir.
4. **Hafiflik ve Performans:** Zengin görsel efektler ve parçacıklar CPU/GPU'yu asla zorlamamalı, düşük donanımlı sistemlerde tamamen kapatılabilmelidir.
