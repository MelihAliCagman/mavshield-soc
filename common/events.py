"""Ortak olay şeması.

bridge/ ve sim/ gördükleri her paketin küçük bir JSON kopyasını ("tap event")
UDP ile detect/ motoruna gönderir; detect/ bu olaylardan güvenlik uyarıları
(Alert) üretip backend/'e POST eder. Üç bileşen de bu modüldeki aynı şemayı
kullanır, böylece format tek bir yerde tanımlı kalır.
"""
from __future__ import annotations

import dataclasses
import json
import time
from typing import Any, Optional


@dataclasses.dataclass
class TapEvent:
    """Bridge veya drone'un bir ağ olayı hakkında gördüğü ham gözlem."""

    src: str                              # "drone" | "bridge"
    kind: str                             # "command" | "command_rejected" |
                                           # "command_relay" | "command_blocked" |
                                           # "telemetry" | "telemetry_relay"
    ts: float = dataclasses.field(default_factory=time.time)
    peer: Optional[str] = None            # kaynağın "ip:port" adresi (varsa)
    local_port: Optional[int] = None
    sysid: Optional[int] = None
    compid: Optional[int] = None
    msg_type: Optional[str] = None
    verified: Optional[bool] = None       # None=imzalama kapalı, True/False=sonuç
    data: dict = dataclasses.field(default_factory=dict)

    def to_json(self) -> bytes:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def from_json(raw: bytes) -> "TapEvent":
        return TapEvent(**json.loads(raw.decode("utf-8")))


@dataclasses.dataclass
class Alert:
    """detect/ motorunun ürettiği, backend/panel'e giden güvenlik uyarısı."""

    rule: str
    severity: str                         # "low" | "medium" | "high" | "critical"
    message: str
    ts: float = dataclasses.field(default_factory=time.time)
    source: Optional[str] = None          # saldırganın "ip:port" adresi
    evidence: dict = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
