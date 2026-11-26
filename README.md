# İHA Haberleşme Güvenliği + Yapay Zeka Destekli SOC

Simüle bir İHA'nın MAVLink haberleşmesine yapılan saldırıları gerçekleştiren,
tespit eden, bir SOC panelinde canlı gösteren, yapay zeka ile raporlayan ve
uçtan uca mesaj imzalama ile savunan bir demo. Ders projesi — Siber Güvenlik
Çözümleri ve Uygulamaları, 2026 Güz.

## Mimari

```
                                    ┌──────────────────────────┐
                                    │   detect/engine.py        │
                     tap (UDP) ───► │  kural motoru + ML        │──┐
                    ╱               └──────────────────────────┘  │ POST /ingest
                   ╱                                               ▼
attacks/*.py ──► bridge/bridge.py ──(udpout)──► sim/drone_sim.py   backend/app.py
(saldırgan)      (şeffaf röle+tap)              (İHA simülatörü)   (FastAPI + WS)
                   ╲                                 ▲                 │
                    ╲── (imzasız ise reddedilir) ─────┘           WS   │ /report
bridge/legit_gcs_demo.py                                           ▼   ▼
(imzalı, yetkili GCS)                                    panel/index.html (React)
```

- **Saldırılar** (`attacks/`) drone'u doğrudan ya da köprü üzerinden hedef alır.
- **Köprü** (`bridge/`) trafiği olduğu gibi iletir ve her paketin küçük bir
  kopyasını tespit motoruna yollar ("tap") — gerçek bir ağ sekmesi/span-port
  gibi davranır.
- **İmzalama savunması** uçtan uca GCS ↔ drone arasındadır (`common/signing.py`):
  köprü ele geçirilse/atlanıp doğrudan drone'a saldırılsa bile sahte komutlar
  **drone'un kendisinde** reddedilir.
- **Tespit motoru** (`detect/`) kural tabanlı sezgiler + hafif bir ML modeliyle
  (IsolationForest) güvenlik olayları üretir.
- **Backend + panel** (`backend/`, `panel/`) olayları toplar, canlı yayınlar ve
  isteğe bağlı olarak Claude ile (yoksa şablonla) Türkçe bir SOC özet raporu
  üretir.

Kavramların ders/BG rehberiyle eşlemesi için bkz. [docs/MAPPING.md](docs/MAPPING.md).

## Dizin yapısı
```
sim/       drone_sim.py     – gerçek MAVLink konuşan hafif drone simülatörü
                               (+ isteğe bağlı komut imzalama doğrulaması)
attacks/   saldırı betikleri: enjeksiyon, GPS spoof, flood (DoS), recon (keşif)
bridge/    şeffaf UDP köprü + tap; legit_gcs_demo.py (imzalı/yetkili GCS örneği)
common/    paylaşılan HMAC imzalama şeması + olay (TapEvent/Alert) tanımları
detect/    kural motoru (rules.py) + ML anomali modeli (ml_model.py)
backend/   FastAPI + WebSocket olay servisi, AI (Claude) destekli rapor uç noktası
panel/     derlemesiz (build-free), tek dosyalık React SOC paneli
docs/      ders/BG Rehberi eşlemesi, bilinen sınırlar
```

## Kurulum
```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Hızlı deneme — temel senaryo (imzalama kapalı, kaçırma mümkün)

Dört terminalde (bu sırayla başlatın):
```bash
# 1) SOC backend'i
uvicorn backend.app:app --port 8000

# 2) tespit motoru
python3 detect/engine.py

# 3) drone simülatörü
python3 sim/drone_sim.py

# 4) köprü
python3 bridge/bridge.py
```

İsteğe bağlı, panel için ayrı bir terminalde:
```bash
python3 -m http.server 5500 --directory panel
# tarayıcıda: http://127.0.0.1:5500
```

Şimdi bir saldırı deneyin:
```bash
python3 attacks/inject_land.py --target 127.0.0.1:14565 --cmd LAND
```
`sim/drone_sim.py` logunda `komut -> mod=LAND` görülür: imzalama yokken drone
sahte komutu kabul eder (kaçırma senaryosu). Panelde (veya `detect/engine.py`
konsolunda) `unauthorized_command_source` uyarısını görürsünüz — **tespit her
zaman açıktır**, imzalamadan bağımsız çalışır.

## Diğer saldırılar

```bash
# GPS/telemetri sahteciliği — fiziksel olarak imkansız konum sıçraması
python3 attacks/spoof_gps.py --target 127.0.0.1:14560

# Komut kanalı seli (DoS)
python3 attacks/flood.py --target 127.0.0.1:14565 --rate 40 --duration 5

# Keşif (recon) taraması
python3 attacks/recon_scan.py --ports 14550-14570
```

Her biri `detect/`'te farklı bir kural tetikler: `gps_jump`, `command_flood`,
`recon_scan` (bkz. [docs/MAPPING.md](docs/MAPPING.md)).

## İmzalama savunmasını açma (Hafta 3 senaryosu)

```bash
python3 sim/drone_sim.py --secret-file secrets/mavlink.key
python3 bridge/bridge.py
```

Saldırı artık reddedilir (köprü üzerinden ya da köprüyü atlayıp doğrudan
drone'a gönderilse bile):
```bash
python3 attacks/inject_land.py --target 127.0.0.1:14565 --cmd LAND   # REDDEDİLİR
python3 attacks/inject_land.py --target 127.0.0.1:14561 --cmd LAND   # yine REDDEDİLİR
```

Yetkili (imzalı) bir istasyon komutu hâlâ kabul edilir:
```bash
python3 bridge/legit_gcs_demo.py --secret-file secrets/mavlink.key --cmd LAND
```

`secrets/` dizini `.gitignore` ile depodan hariç tutulmuştur — anahtar dosyası
hiçbir zaman commit edilmemelidir.

## AI destekli rapor

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # yoksa şablon tabanlı rapor üretilir
curl http://127.0.0.1:8000/report
```

Panelin sağ tarafındaki "AI Rapor Oluştur" butonu aynı uç noktayı çağırır ve
`generated_by` alanına göre (Claude / şablon) kaynağını açıkça belirtir.

## Durum
- [x] Drone simülatörü (telemetri + komut tepkisi)
- [x] Saldırı #1: yetkisiz komut enjeksiyonu
- [x] Saldırı #2: GPS/telemetri sahteciliği (spoofing)
- [x] Saldırı #3: komut kanalı seli (DoS/flood)
- [x] Saldırı #4: keşif (recon) taraması
- [x] Köprü (şeffaf röle + tap)
- [x] Tespit motoru (kural tabanlı + ML/IsolationForest)
- [x] Backend (FastAPI + WebSocket) + SOC paneli (React, derlemesiz)
- [x] AI destekli (Claude, şablona düşen) raporlama
- [x] Uçtan uca mesaj imzalama savunması (HMAC, defense-in-depth)
- [ ] Kalıcı veri deposu (şu an bellek içi; yeniden başlatınca olaylar silinir)
- [ ] Telemetri yönünün de imzalanması (bkz. docs/MAPPING.md "Bilinen sınırlar")
