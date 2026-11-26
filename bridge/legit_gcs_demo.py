#!/usr/bin/env python3
"""
Yetkili yer istasyonunu (GCS) taklit eden demo gönderici.

attacks/inject_land.py'den farkı: burada komut, common/signing.py'deki
paylaşılan gizli anahtarla imzalanıp HMAC zarfına sarılıyor. İmzalama
savunması (Hafta 3) açıldığında drone BU komutu kabul eder — saldırı
betiklerinin aksine (onlar anahtarı bilmediği için geçerli imza üretemez).

Kullanım:
  # Önce anahtarı üret (veya drone_sim/bridge zaten üretmiş olsun):
  python3 -c "import sys; sys.path.insert(0,'.'); from common import signing as s; s.load_or_create_key('secrets/mavlink.key')"

  python3 bridge/legit_gcs_demo.py --secret-file secrets/mavlink.key --cmd LAND
"""
import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import signing as sig  # noqa: E402
from pymavlink.dialects.v20 import common as mavlink2  # noqa: E402

GCS_SYSID = 7  # "resmi" yer istasyonunun sistem kimliği
GCS_COMPID = mavlink2.MAV_COMP_ID_MISSIONPLANNER

CMDS = {
    "LAND": (mavlink2.MAV_CMD_NAV_LAND, [0, 0, 0, 0, 0, 0, 0]),
    "RTL": (mavlink2.MAV_CMD_NAV_RETURN_TO_LAUNCH, [0, 0, 0, 0, 0, 0, 0]),
    "ARM": (mavlink2.MAV_CMD_COMPONENT_ARM_DISARM, [1, 0, 0, 0, 0, 0, 0]),
    "DISARM": (mavlink2.MAV_CMD_COMPONENT_ARM_DISARM, [0, 0, 0, 0, 0, 0, 0]),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="127.0.0.1:14565",
                     help="köprünün GCS komut girişi")
    ap.add_argument("--secret-file", required=True)
    ap.add_argument("--cmd", default="LAND", choices=list(CMDS.keys()))
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    secret = sig.load_or_create_key(args.secret_file)
    host, port_s = args.target.rsplit(":", 1)
    port = int(port_s)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    mav = mavlink2.MAVLink(None, srcSystem=GCS_SYSID, srcComponent=GCS_COMPID)
    mav.robust_parsing = True
    cmd_id, params = CMDS[args.cmd]

    print(f"[gcs] yetkili istasyon (sysid={GCS_SYSID}) imzalı komut gönderiyor "
          f"-> {args.target}")
    for i in range(args.repeat):
        msg = mav.command_long_encode(1, mavlink2.MAV_COMP_ID_AUTOPILOT1,
                                        cmd_id, 0, *params)
        raw = msg.pack(mav)
        envelope = sig.sign_payload(secret, raw)
        sock.sendto(envelope, (host, port))
        print(f"[gcs] imzalı {args.cmd} gönderildi ({i + 1}/{args.repeat})")
        time.sleep(0.5)
    print("[gcs] tamam.")


if __name__ == "__main__":
    main()
