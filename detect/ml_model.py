"""Basit ML tabanlı telemetri anomali tespiti.

Kural tabanlı tespitin (rules.py) eşik koyarak yakaladığı belirli örüntülerin
dışında kalan, genel "bu telemetri normalden farklı görünüyor" durumlarını
yakalamak için hafif bir IsolationForest modeli. Gerçek bir uçuş veri seti
yerine, makul bir normal uçuş zarfını taklit eden sentetik verilerle
başlangıçta eğitilir. Amaç gerçek bir SOTA anomali dedektörü değil, ML
katmanının mimaride nereye oturduğunu göstermektir — gerçek bir sistemde bu
model gerçek telemetri logları üzerinde eğitilir.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
from sklearn.ensemble import IsolationForest

FEATURES = ("alt", "ground_speed", "battery")


def _synthetic_baseline(n: int = 400) -> np.ndarray:
    rng = np.random.default_rng(42)
    alt = rng.normal(50, 8, n).clip(0, 120)
    speed = rng.normal(12, 3, n).clip(0, 25)
    battery = np.linspace(100, 20, n) + rng.normal(0, 2, n)
    return np.column_stack([alt, speed, battery])


class TelemetryAnomalyModel:
    def __init__(self) -> None:
        self.model = IsolationForest(
            n_estimators=100, contamination=0.03, random_state=42)
        self.model.fit(_synthetic_baseline())

    def score(self, telemetry: dict) -> Tuple[bool, float]:
        """(anomali_mi, skor) döner. Skor ne kadar düşükse o kadar anormal."""
        if not all(f in telemetry for f in FEATURES):
            return False, 0.0
        x = np.array([[telemetry.get(f, 0.0) for f in FEATURES]])
        pred = self.model.predict(x)[0]                      # -1 anomali, 1 normal
        score = float(self.model.decision_function(x)[0])
        return pred == -1, score
