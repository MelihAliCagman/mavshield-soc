#!/usr/bin/env python3
"""
Saldırı #4 — Keşif (recon) taraması.

Saldırgan, hedef ağdaki MAVLink uç noktalarını bulmak için bir port
aralığına (varsayılan: 14550-14570) kısa MAVLink HEARTBEAT paketleri
gönderir. Gerçek bir ortamda bu, "hangi portlar MAVLink konuşuyor" sorusuna
cevap arayan, genellikle asıl saldırıdan önce gelen bir ön keşif adımıdır.

detect/rules.py'deki recon_scan kuralı, aynı kaynaktan kısa bir zaman
penceresinde birden fazla FARKLI porta erişim olduğunda alarm üretir. Bu
korelasyon detect/engine.py'de (merkezi noktada) kurulur çünkü her süreç
(bridge, drone) sadece kendi dinlediği tek portu görür — taramanın tamamını
yalnızca tüm tap olaylarını toplayan tespit motoru görebilir.

Kullanım:
  python3 attacks/recon_scan.py --host 127.0.0.1 --ports 14550-14570
  python3 attacks/recon_scan.py --ports 14560,14561,14565   # bilinen portlara hızlı tarama
"""
import argparse
import socket
import time

from pymavlink.dialects.v20 import common as mavlink2

ATTACKER_SYSID = 254
ATTACKER_COMPID = 190


def _parse_ports(spec: str):
    ports = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            ports.extend(range(int(a), int(b) + 1))
        else:
            ports.append(int(part))
    return ports


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ports", default="14550-14570",
                     help="taranacak port aralığı/listesi, ör. 14550-14570 ya da 14560,14561,14565")
    ap.add_argument("--delay", type=float, default=0.15, help="portlar arası bekleme (sn)")
    args = ap.parse_args()

    ports = _parse_ports(args.ports)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    mav = mavlink2.MAVLink(None, srcSystem=ATTACKER_SYSID, srcComponent=ATTACKER_COMPID)
    mav.robust_parsing = True
    probe = mav.heartbeat_encode(
        mavlink2.MAV_TYPE_GCS, mavlink2.MAV_AUTOPILOT_INVALID, 0, 0, 0).pack(mav)

    print(f"[saldiri] keşif taraması: {args.host}, {len(ports)} port "
          f"({ports[0]}-{ports[-1]})")
    hit = 0
    for port in ports:
        try:
            sock.sendto(probe, (args.host, port))
            hit += 1
        except OSError:
            pass
        time.sleep(args.delay)
    print(f"[saldiri] tamam, {hit} porta prob gönderildi.")


if __name__ == "__main__":
    main()
