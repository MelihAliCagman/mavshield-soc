#!/usr/bin/env python3
"""
Tespit motoru — bridge/ ve sim/'den gelen "tap" olaylarını UDP üzerinden
dinler, kural tabanlı (rules.py) ve ML tabanlı (ml_model.py) tespiti uygular,
ürettiği güvenlik uyarılarını (Alert) backend/'e POST eder.

Kullanım:
  python3 detect/engine.py
  python3 detect/engine.py --listen 127.0.0.1:14600 --backend http://127.0.0.1:8000
  python3 detect/engine.py --no-backend   # backend çalışmıyorsa, sadece konsola yaz
"""
import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.events import Alert, TapEvent  # noqa: E402
from detect.ml_model import TelemetryAnomalyModel  # noqa: E402
from detect.rules import RuleEngine  # noqa: E402

SEVERITY_TAG = {"low": "DÜŞÜK", "medium": "ORTA", "high": "YÜKSEK", "critical": "KRİTİK"}


def post_alert(backend_url: str, alert: Alert) -> None:
    body = json.dumps(alert.to_dict(), default=str).encode("utf-8")
    req = urllib.request.Request(
        f"{backend_url.rstrip('/')}/ingest", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=1.0)
    except urllib.error.URLError as e:
        print(f"[detect] backend'e ulaşılamadı ({e}); uyarı sadece konsola yazıldı.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:14600")
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--no-backend", action="store_true",
                     help="sadece konsola yaz, backend'e POST etme")
    args = ap.parse_args()

    host, port = args.listen.rsplit(":", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, int(port)))

    rules = RuleEngine()
    ml = TelemetryAnomalyModel()
    ml_last_alert: dict = {}
    ML_COOLDOWN_S = 15.0

    print(f"[detect] dinleniyor: {args.listen}")
    print(f"[detect] backend: {'kapalı (--no-backend)' if args.no_backend else args.backend}")

    while True:
        data, _ = sock.recvfrom(4096)
        try:
            evt = TapEvent.from_json(data)
        except Exception as e:
            print(f"[detect] bozuk olay atlandı: {e}")
            continue

        alerts = rules.process(evt)

        if evt.kind == "telemetry":
            is_anom, score = ml.score(evt.data)
            last = ml_last_alert.get(evt.sysid)
            throttled = last is not None and (evt.ts - last) < ML_COOLDOWN_S
            if is_anom and not throttled:
                ml_last_alert[evt.sysid] = evt.ts
                alerts.append(Alert(
                    rule="telemetry_anomaly_ml",
                    severity="medium",
                    message=(f"sysid={evt.sysid} telemetrisinde ML modeline göre anomali "
                             f"(skor={score:.3f})."),
                    source=evt.peer,
                    evidence={"score": score, "telemetry": evt.data},
                ))

        for alert in alerts:
            tag = SEVERITY_TAG.get(alert.severity, alert.severity.upper())
            print(f"[detect] [{tag}] {alert.rule}: {alert.message}")
            if not args.no_backend:
                post_alert(args.backend, alert)


if __name__ == "__main__":
    main()
