"""Uçtan uca MAVLink komut imzalama (HMAC-SHA256 zarf).

MAVLink2'nin kendi yerleşik imzalama alanı yerine, ders kapsamında okunması ve
anlatılması kolay, kendi yazdığımız basit bir zarf (envelope) formatı
kullanıyoruz:

    MAGIC(5B) | timestamp_ms(8B, big-endian) | HMAC-SHA256(32B) | mavlink_payload

HMAC, (mavlink_payload + timestamp_ms) üzerinden paylaşılan gizli anahtarla
hesaplanır. Bu bize üç şeyi birden verir:

  - Bütünlük:        payload değişirse imza tutmaz.
  - Kimlik doğrulama: gizli anahtarı bilmeyen bir saldırgan geçerli imza
                      üretemez (bkz. attacks/inject_land.py).
  - Replay koruması: zaman damgası çok eskiyse zarf reddedilir.

İmzalama uçtan uca GCS <-> drone arasında uygulanır (bkz. bridge/legit_gcs_demo.py
ve sim/drone_sim.py); köprü (bridge/bridge.py) sadece isteğe bağlı olarak erken
eleme yapar — asıl yetkilendirme kararı her zaman drone'dadır. Böylece köprü ele
geçirilse bile sahte komutlar drone tarafında reddedilir.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import os
import time
from pathlib import Path
from typing import Optional, Tuple

MAGIC = b"MSIG1"
TS_LEN = 8
MAC_LEN = 32
HEADER_LEN = len(MAGIC) + TS_LEN + MAC_LEN


def load_or_create_key(path: str) -> bytes:
    """Paylaşılan gizli anahtarı dosyadan okur; dosya yoksa rastgele üretip kaydeder.

    Anahtar hex-encoded 32 bayt (256 bit) olarak saklanır. Bu dosya .gitignore
    ile depoya dahil edilmemelidir — gerçek bir sistemde anahtar güvenli bir
    anahtar kasasında (HSM, Vault, vb.) tutulur.
    """
    p = Path(path)
    if p.exists():
        return bytes.fromhex(p.read_text().strip())
    p.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    p.write_text(key.hex())
    return key


def sign_payload(secret: bytes, payload: bytes) -> bytes:
    """`payload` baytlarını imzalı bir zarfa sarar."""
    ts = int(time.time() * 1000).to_bytes(TS_LEN, "big")
    mac = _hmac.new(secret, payload + ts, hashlib.sha256).digest()
    return MAGIC + ts + mac + payload


def verify_envelope(
    secret: bytes, data: bytes, max_skew_ms: int = 5000
) -> Tuple[Optional[bytes], str]:
    """Bir zarfı doğrular.

    Dönüş: (orijinal_payload, "ok") başarılıysa; (None, sebep) değilse.
    Olası sebepler: "no_signature", "bad_signature", "stale_or_replay".
    """
    if len(data) < HEADER_LEN or not data.startswith(MAGIC):
        return None, "no_signature"
    ts_raw = data[len(MAGIC): len(MAGIC) + TS_LEN]
    mac = data[len(MAGIC) + TS_LEN: HEADER_LEN]
    payload = data[HEADER_LEN:]
    expected = _hmac.new(secret, payload + ts_raw, hashlib.sha256).digest()
    if not _hmac.compare_digest(mac, expected):
        return None, "bad_signature"
    ts_ms = int.from_bytes(ts_raw, "big")
    if abs(int(time.time() * 1000) - ts_ms) > max_skew_ms:
        return None, "stale_or_replay"
    return payload, "ok"
