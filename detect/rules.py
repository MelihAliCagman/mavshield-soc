"""Kural tabanlı tespit mantığı.

Her kural, gelen TapEvent akışına (tek bir olaydan ya da küçük bir pencereden)
bakarak şüpheli davranışı yakalar. Bilinçli olarak basit ve açıklaması kolay
sezgisel kurallar kullanıyoruz; ML modeli (ml_model.py) bunları tamamlayan,
eşik koymadan genel telemetri anomalilerini yakalayan ikinci bir katmandır.

Kurallar:
  - unsigned_command_rejected    : imzalama açıkken doğrulanamayan komut
  - unauthorized_command_source  : yetkili GCS sysid'i dışından gelen komut
  - command_flood                : aynı kaynaktan kısa sürede çok sayıda komut
  - recon_scan                   : aynı kaynağın kısa sürede birden çok farklı
                                    porta erişmesi (keşif taraması)
  - gps_jump                     : art arda telemetri örnekleri arasında
                                    fiziksel olarak mümkün olmayan konum sıçraması
"""
from __future__ import annotations

import collections
import math
import time
from typing import Deque, Dict, List

from common.events import Alert, TapEvent

# "Resmi" yer istasyonunun sistem kimliği (bkz. bridge/legit_gcs_demo.py).
ALLOWED_GCS_SYSIDS = {7}

# Saldırı betiklerinin kullandığı tipik sahte kimlik (bkz. attacks/inject_land.py).
KNOWN_ATTACKER_SYSIDS = {255}

COMMAND_FLOOD_WINDOW_S = 5.0
COMMAND_FLOOD_THRESHOLD = 8          # pencere içinde bu sayıdan fazla komut -> flood

RECON_WINDOW_S = 10.0
RECON_DISTINCT_PORTS_THRESHOLD = 3   # aynı kaynaktan bu kadar farklı port -> keşif

GPS_JUMP_MAX_SPEED_MPS = 60.0        # bu "hız"ı aşan konum sıçraması şüpheli


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class RuleEngine:
    """Her kaynak (ip) için küçük bir durum tutar; süreklilik gerektiren
    kuralları (flood, recon, gps_jump) değerlendirmek için kullanılır."""

    def __init__(self) -> None:
        self._cmd_times: Dict[str, Deque[float]] = collections.defaultdict(
            lambda: collections.deque(maxlen=200))
        self._ports_seen: Dict[str, Dict[int, float]] = collections.defaultdict(dict)
        self._last_telem: Dict[int, dict] = {}
        self._last_alert: Dict[tuple, float] = {}

    def _throttled(self, key: tuple, now: float, cooldown: float) -> bool:
        """Aynı (kural, kaynak) için kısa sürede tekrar tekrar alarm basılmasını
        önler — bir flood/tarama tek bir saldırı olarak bir kez raporlanır,
        her paket için ayrı ayrı değil."""
        last = self._last_alert.get(key)
        if last is not None and now - last < cooldown:
            return True
        self._last_alert[key] = now
        return False

    def process(self, evt: TapEvent) -> List[Alert]:
        alerts: List[Alert] = []
        now = evt.ts or time.time()
        host = evt.peer.split(":")[0] if evt.peer else None

        # Port takibi (keşif/recon) TÜM olay türleri için yapılır: bir
        # saldırgan telemetri portuna (14560), komut portuna (14561/14565)
        # art arda dokunabilir — tespit için hangi MAVLink mesaj tipini
        # gönderdiği değil, kaç farklı porta eriştiği önemlidir.
        if host and evt.local_port:
            ports = self._ports_seen[host]
            ports[evt.local_port] = now
            recent_ports = {p for p, t in ports.items() if now - t <= RECON_WINDOW_S}
            if (len(recent_ports) >= RECON_DISTINCT_PORTS_THRESHOLD
                    and not self._throttled(("recon_scan", host), now, RECON_WINDOW_S)):
                alerts.append(Alert(
                    rule="recon_scan",
                    severity="medium",
                    message=(f"{host} adresi {RECON_WINDOW_S:.0f} sn içinde "
                             f"{len(recent_ports)} farklı porta erişti — "
                             f"olası keşif taraması."),
                    source=evt.peer,
                    evidence={"ports": sorted(recent_ports)},
                ))

        if evt.kind in ("command", "command_relay", "command_blocked", "command_rejected"):
            if host:
                dq = self._cmd_times[host]
                dq.append(now)
                recent = [t for t in dq if now - t <= COMMAND_FLOOD_WINDOW_S]
                if (len(recent) >= COMMAND_FLOOD_THRESHOLD
                        and not self._throttled(("command_flood", host), now, COMMAND_FLOOD_WINDOW_S)):
                    alerts.append(Alert(
                        rule="command_flood",
                        severity="high",
                        message=(f"{host} adresinden {COMMAND_FLOOD_WINDOW_S:.0f} sn içinde "
                                 f"{len(recent)} komut — olası DoS/flood saldırısı."),
                        source=evt.peer,
                        evidence={"count": len(recent), "window_s": COMMAND_FLOOD_WINDOW_S},
                    ))

            if evt.verified is False:
                if not self._throttled(("unsigned_command_rejected", host), now, 3.0):
                    alerts.append(Alert(
                        rule="unsigned_command_rejected",
                        severity="critical",
                        message=f"{evt.peer or '?'} kaynağından imzasız/geçersiz komut reddedildi.",
                        source=evt.peer,
                        evidence={"reason": evt.data.get("reason"), "msg_type": evt.msg_type},
                    ))
            elif evt.kind == "command" and evt.sysid is not None:
                if evt.sysid in KNOWN_ATTACKER_SYSIDS or evt.sysid not in ALLOWED_GCS_SYSIDS:
                    if not self._throttled(("unauthorized_command_source", host, evt.sysid), now, 3.0):
                        alerts.append(Alert(
                            rule="unauthorized_command_source",
                            severity="high",
                            message=(f"Beklenmeyen sistem kimliğinden (sysid={evt.sysid}) komut "
                                     f"alındı — yetkili GCS değil."),
                            source=evt.peer,
                            evidence={"sysid": evt.sysid, "command": evt.data.get("command")},
                        ))

        elif evt.kind == "telemetry" and evt.sysid is not None and "lat" in evt.data:
            prev = self._last_telem.get(evt.sysid)
            cur = evt.data
            self._last_telem[evt.sysid] = {**cur, "_ts": now}
            if prev is not None:
                dt = max(now - prev.get("_ts", now), 0.05)
                dist_m = _haversine_m(prev["lat"], prev["lon"], cur["lat"], cur["lon"])
                speed = dist_m / dt
                if speed > GPS_JUMP_MAX_SPEED_MPS:
                    alerts.append(Alert(
                        rule="gps_jump",
                        severity="high",
                        message=(f"sysid={evt.sysid} için konum sıçraması tespit edildi "
                                 f"(~{speed:.0f} m/s) — GPS spoofing şüphesi."),
                        source=evt.peer,
                        evidence={"speed_mps": round(speed, 1), "dt_s": round(dt, 2)},
                    ))

        return alerts
