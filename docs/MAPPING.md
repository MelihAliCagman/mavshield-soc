# Ders / Bilgi Güvenliği Rehberi Eşlemesi

Bu belge, projedeki her bileşenin hangi temel siber güvenlik kavramını
gösterdiğini özetler — raporda "neden bu mimari" sorusuna hızlı cevap
vermek içindir.

## NIST Siber Güvenlik Çerçevesi (Identify / Protect / Detect / Respond / Recover)

| Fonksiyon | Projedeki karşılığı |
|---|---|
| **Identify**  | `docs/MAPPING.md`, mimari diyagramı (README) — varlıklar (drone, GCS, haberleşme kanalı) ve tehdit yüzeyi tanımlanır. |
| **Protect**   | `common/signing.py` + `bridge/legit_gcs_demo.py` + `sim/drone_sim.py` — HMAC tabanlı uçtan uca komut imzalama/kimlik doğrulama. |
| **Detect**    | `detect/rules.py` (sezgisel kurallar) + `detect/ml_model.py` (IsolationForest ile anomali tespiti). |
| **Respond**   | `backend/app.py` + `panel/index.html` — olayların canlı görünürlüğü; `backend/ai_report.py` — AI destekli özetleme, triage'a yardımcı olur. |
| **Recover**   | Kapsam dışı (ders projesi); gerçek bir sistemde burada "fail-safe RTL", "watchdog" gibi mekanizmalar olurdu. |

## CIA Üçlüsü (Gizlilik / Bütünlük / Erişilebilirlik)

| Özellik | Saldırı | Savunma / Tespit |
|---|---|---|
| **Bütünlük**        | `attacks/inject_land.py` — yetkisiz komut enjeksiyonu | `common/signing.py` (HMAC) → `unsigned_command_rejected` kuralı |
| **Kimlik doğrulama**| `attacks/inject_land.py` (sahte sysid=255)            | `unauthorized_command_source` kuralı |
| **Bütünlük (telemetri)** | `attacks/spoof_gps.py` — GPS sahteciliği         | `gps_jump` kuralı (fiziksel olarak imkânsız konum sıçraması) |
| **Erişilebilirlik** | `attacks/flood.py` — komut kanalı seli (DoS)          | `command_flood` kuralı (hacim/oran bazlı eşik) |
| **Gizlilik / Keşif** | `attacks/recon_scan.py` — port/servis keşfi          | `recon_scan` kuralı (aynı kaynaktan çoklu port erişimi) |

## MITRE ATT&CK (ICS/Drone bağlamına uyarlanmış, kavramsal)

- **Reconnaissance**        → `attacks/recon_scan.py`
- **Initial Access / Spoof**→ `attacks/spoof_gps.py`
- **Command and Control**   → saldırganın drone'a doğrudan komut göndermesi (`attacks/inject_land.py`)
- **Impact (DoS)**          → `attacks/flood.py`
- **Impact (Loss of Control)** → imzasız `LAND`/`DISARM` komutunun kabul edilmesi (savunma kapalıyken)

## Savunma derinliği (defense in depth)

İmzalama kontrolü bilinçli olarak **iki katmanda** uygulanır:

1. **Drone (`sim/drone_sim.py`)** — asıl yetkilendirme kararı burada verilir;
   köprü atlanıp doğrudan drone'a saldırılsa bile komut reddedilir.
2. **Köprü (`bridge/bridge.py`, `--enforce`)** — isteğe bağlı erken eleme;
   drone'u gereksiz yükten kurtarır ama tek başına güvenlik sınırı DEĞİLDİR.

Bu tasarım, "güvenliği tek bir bileşene (köprüye) güvenerek kurma" hatasından
kaçınır: köprü ele geçirilse/bypass edilse bile uçtan uca imzalama ayakta
kalır.

## Bilinen sınırlar (gelecek çalışma için)

- Telemetri (drone -> GCS yönü) imzasızdır; yalnızca komut yönü (GCS -> drone)
  korunur. Gerçek bir sistemde aynı HMAC şeması iki yönde de uygulanır.
- Tüm bileşenler `127.0.0.1` üzerinde simüle edilir; gerçek bir radyo bağlantısı
  (ör. SiK telemetri, LTE) farklı gecikme/paket kaybı karakteristiklerine sahiptir.
- ML modeli sentetik bir temel çizgiyle eğitilir; gerçek bir sistemde gerçek uçuş
  logları kullanılır.
- Anahtar yönetimi basittir (tek paylaşılan HMAC anahtarı, dosyada düz metin
  hex); gerçek bir sistemde anahtar rotasyonu, HSM/Vault ve asimetrik imzalama
  (ed25519) tercih edilir.
