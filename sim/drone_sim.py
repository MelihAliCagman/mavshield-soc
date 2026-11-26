#!/usr/bin/env python3
"""
Basit İHA (drone) MAVLink simülatörü.

Gerçek ArduPilot SITL yerine, tek dosyada çalışan, gerçek MAVLink 2 konuşan
hafif bir simülatör. Bir görev rotasında uçar, telemetri yayınlar ve gelen
komutlara (ARM/DISARM, LAND, RTL, mod değişimi) tepki verir.

Köprü (bridge) ile UDP üzerinden konuşur:
  - Bu simülatör:  udpout -> bridge'in dinlediği port (varsayılan 14560)
  - Komutları:     udpin  <- bridge (varsayılan 14561)

İmzalama savunması (Hafta 3):
  --secret-file verilirse, gelen her komutun common/signing.py'deki HMAC
  zarfıyla imzalanmış olması beklenir. Zarf doğrulanamazsa komut SESSİZCE
  (drone durumunu değiştirmeden) reddedilir ve tespit motoruna bir
  "command_rejected" olayı gönderilir. --secret-file verilmezse (varsayılan),
  davranış Hafta 1-2 ile aynıdır: her komut doğrulamasız kabul edilir
  (kaçırma senaryosu açık).

Tespit entegrasyonu (Hafta 2):
  Her gelen komut ve düzenli telemetri örnekleri, --tap adresine (varsayılan
  127.0.0.1:14600) küçük bir JSON kopyası olarak gönderilir; detect/engine.py
  bunları dinler.

Kullanım:
  python3 sim/drone_sim.py --out 127.0.0.1:14560 --in 127.0.0.1:14561
  python3 sim/drone_sim.py --secret-file secrets/mavlink.key   # imzalama açık
"""
import argparse
import math
import socket
import sys
import time
from pathlib import Path

from pymavlink import mavutil
from pymavlink.dialects.v20 import common as mavlink2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import events as ev  # noqa: E402
from common import signing as sig  # noqa: E402

SYSID = 1
COMPID = mavlink2.MAV_COMP_ID_AUTOPILOT1


def _hostport(s: str):
    host, port = s.rsplit(":", 1)
    return host, int(port)


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
    ap.add_argument("--secret-file", default=None,
                     help="verilirse komutlar HMAC zarfıyla doğrulanır (Hafta 3)")
    ap.add_argument("--tap", default="127.0.0.1:14600",
                     help="tespit motorunun dinlediği adres")
    ap.add_argument("--no-tap", action="store_true", help="tap olaylarını kapat")
    args = ap.parse_args()

    tx = mavutil.mavlink_connection("udpout:" + args.out, source_system=SYSID,
                                    source_component=COMPID, dialect="common")

    cmd_host, cmd_port = _hostport(args.inp)
    cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cmd_sock.bind((cmd_host, cmd_port))
    cmd_sock.setblocking(False)
    cmd_parser = mavlink2.MAVLink(None)
    cmd_parser.robust_parsing = True

    secret = sig.load_or_create_key(args.secret_file) if args.secret_file else None

    tap_addr = None if args.no_tap else _hostport(args.tap)
    tap_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if tap_addr else None

    def emit_tap(kind, **kw):
        if not tap_sock:
            return
        try:
            evt = ev.TapEvent(src="drone", kind=kind, **kw)
            tap_sock.sendto(evt.to_json(), tap_addr)
        except OSError:
            pass

    st = DroneState()
    # Başlangıçta ARM + AUTO (demo için direkt uçuşa hazır)
    st.armed = True
    period = 1.0 / args.rate
    last = time.time()
    hb_last = 0.0
    print(f"[sim] drone başladı, telemetri -> {args.out}, komut <- {args.inp}")
    print(f"[sim] imzalama={'AÇIK' if secret else 'kapalı (kaçırmaya açık)'}, "
          f"tap={'kapalı' if not tap_sock else args.tap}")

    while True:
        now = time.time()
        dt = now - last
        last = now
        st.step(dt)

        # --- Gelen komutları işle ---
        while True:
            try:
                data, peer = cmd_sock.recvfrom(4096)
            except BlockingIOError:
                break
            peer_s = f"{peer[0]}:{peer[1]}"

            verified = None
            payload = data
            if secret is not None:
                unwrapped, reason = sig.verify_envelope(secret, data)
                if unwrapped is None:
                    print(f"[sim] REDDEDİLDİ ({reason}) <- {peer_s}")
                    emit_tap("command_rejected", peer=peer_s, local_port=cmd_port,
                             verified=False, data={"reason": reason})
                    continue
                verified = True
                payload = unwrapped

            try:
                msgs = cmd_parser.parse_buffer(payload) or []
            except Exception:
                msgs = []

            # Alınan HER paket için bir tap olayı üret — mesaj tipi ne olursa
            # olsun (flood/recon tespiti, trafik hacmine/porta bakar, tek
            # başına COMMAND_LONG'a değil). Ayrıştırılamayan/anlamsız baytlar
            # (ör. bir keşif taramasının gönderdiği rastgele veri) bile
            # msg_type=None ile tapa yansır.
            first = msgs[0] if msgs else None
            emit_tap(
                "command", peer=peer_s, local_port=cmd_port, verified=verified,
                sysid=first.get_srcSystem() if first else None,
                compid=first.get_srcComponent() if first else None,
                msg_type=first.get_type() if first else None,
                data={"n_msgs": len(msgs), "bytes": len(payload)},
            )

            for msg in msgs:
                t = msg.get_type()
                if t == "COMMAND_LONG":
                    cmd = msg.command
                    if cmd == mavlink2.MAV_CMD_COMPONENT_ARM_DISARM:
                        st.armed = bool(msg.param1 >= 0.5)
                        print(f"[sim] ARM/DISARM -> armed={st.armed}")
                    elif cmd in MODE_MAP:
                        st.mode = MODE_MAP[cmd]
                        print(f"[sim] komut -> mod={st.mode}")

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
        emit_tap(
            "telemetry", sysid=SYSID, compid=COMPID, msg_type="GLOBAL_POSITION_INT",
            data={"lat": st.lat, "lon": st.lon, "alt": round(st.alt, 2),
                  "ground_speed": st.ground_speed, "battery": round(st.battery, 2),
                  "armed": st.armed, "mode": st.mode},
        )

        tx.mav.sys_status_send(
            0, 0, 0, 0,
            int(st.battery * 100) if False else 11000,  # voltaj mV (sabit)
            -1, int(st.battery), 0, 0, 0, 0, 0, 0,
        )
        time.sleep(period)


if __name__ == "__main__":
    main()
