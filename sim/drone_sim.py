#!/usr/bin/env python3
"""
Basit İHA (drone) MAVLink simülatörü.

Gerçek ArduPilot SITL yerine, tek dosyada çalışan, gerçek MAVLink 2 konuşan
hafif bir simülatör. Bir görev rotasında uçar, telemetri yayınlar ve gelen
komutlara (ARM/DISARM, LAND, RTL, mod değişimi) tepki verir.

Köprü (bridge) ile UDP üzerinden konuşur:
  - Bu simülatör:  udpout -> bridge'in dinlediği port (varsayılan 14560)
  - Komutları:     udpin  <- bridge (varsayılan 14561)

Kullanım:
  python3 drone_sim.py --out 127.0.0.1:14560 --in 127.0.0.1:14561
"""
import argparse
import math
import time

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink2

SYSID = 1
COMPID = mavlink2.MAV_COMP_ID_AUTOPILOT1


class DroneState:
    def __init__(self):
        self.armed = False
        self.mode = "AUTO"          # AUTO, LAND, RTL, GUIDED
        self.lat = 39.925018        # Ankara civarı başlangıç
        self.lon = 32.836956
        self.alt = 0.0              # metre (AGL)
        self.target_alt = 50.0
        self.heading = 90.0         # derece
        self.ground_speed = 0.0
        self.battery = 100.0
        self.t0 = time.time()
        self.boot_ms = 0

    def step(self, dt):
        self.boot_ms = int((time.time() - self.t0) * 1000)
        if not self.armed:
            self.ground_speed = 0.0
            return
        # Uçuş mantığı
        if self.mode == "AUTO":
            # tırman ve ileri uç
            if self.alt < self.target_alt:
                self.alt = min(self.target_alt, self.alt + 5.0 * dt)
            self.ground_speed = 12.0
        elif self.mode in ("LAND", "RTL"):
            # in
            self.alt = max(0.0, self.alt - 4.0 * dt)
            self.ground_speed = 6.0 if self.alt > 1 else 0.0
            if self.alt <= 0.1:
                self.armed = False
        # konumu ilerlet (basit düz uçuş)
        d = self.ground_speed * dt  # metre
        dlat = (d * math.cos(math.radians(self.heading))) / 111320.0
        dlon = (d * math.sin(math.radians(self.heading))) / (
            111320.0 * math.cos(math.radians(self.lat))
        )
        self.lat += dlat
        self.lon += dlon
        self.battery = max(0.0, self.battery - 0.05 * dt)


MODE_MAP = {
    mavlink2.MAV_CMD_NAV_LAND: "LAND",
    mavlink2.MAV_CMD_NAV_RETURN_TO_LAUNCH: "RTL",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="127.0.0.1:14560",
                    help="telemetriyi göndereceği adres (bridge girişi)")
    ap.add_argument("--in", dest="inp", default="127.0.0.1:14561",
                    help="komutları dinleyeceği adres")
    ap.add_argument("--rate", type=float, default=10.0, help="telemetri Hz")
    args = ap.parse_args()

    tx = mavutil.mavlink_connection("udpout:" + args.out, source_system=SYSID,
                                    source_component=COMPID, dialect="common")
    rx = mavutil.mavlink_connection("udpin:" + args.inp, dialect="common")

    st = DroneState()
    # Başlangıçta ARM + AUTO (demo için direkt uçuşa hazır)
    st.armed = True
    period = 1.0 / args.rate
    last = time.time()
    hb_last = 0.0
    print(f"[sim] drone başladı, telemetri -> {args.out}, komut <- {args.inp}")

    while True:
        now = time.time()
        dt = now - last
        last = now
        st.step(dt)

        # --- Gelen komutları işle ---
        msg = rx.recv_match(blocking=False)
        while msg is not None:
            t = msg.get_type()
            if t == "COMMAND_LONG":
                cmd = msg.command
                if cmd == mavlink2.MAV_CMD_COMPONENT_ARM_DISARM:
                    st.armed = bool(msg.param1 >= 0.5)
                    print(f"[sim] ARM/DISARM -> armed={st.armed}")
                elif cmd in MODE_MAP:
                    st.mode = MODE_MAP[cmd]
                    print(f"[sim] komut -> mod={st.mode}")
            elif t == "SET_MODE":
                pass
            msg = rx.recv_match(blocking=False)

        # --- Telemetri gönder ---
        if now - hb_last >= 1.0:
            tx.mav.heartbeat_send(
                mavlink2.MAV_TYPE_QUADROTOR,
                mavlink2.MAV_AUTOPILOT_ARDUPILOTMEGA,
                mavlink2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                | (mavlink2.MAV_MODE_FLAG_SAFETY_ARMED if st.armed else 0),
                0,
                mavlink2.MAV_STATE_ACTIVE if st.armed else mavlink2.MAV_STATE_STANDBY,
            )
            hb_last = now

        tx.mav.global_position_int_send(
            st.boot_ms,
            int(st.lat * 1e7),
            int(st.lon * 1e7),
            int(st.alt * 1000),
            int(st.alt * 1000),
            0, 0, 0,
            int(st.heading * 100),
        )
        tx.mav.sys_status_send(
            0, 0, 0, 0,
            int(st.battery * 100) if False else 11000,  # voltaj mV (sabit)
            -1, int(st.battery), 0, 0, 0, 0, 0, 0,
        )
        time.sleep(period)


if __name__ == "__main__":
    main()
