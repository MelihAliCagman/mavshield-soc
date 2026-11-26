#!/usr/bin/env python3
"""
Köprü (bridge) — drone ile yer istasyonu (GCS) arasında UDP paket aktarır.

Köprü, geçen her paketin küçük bir JSON kopyasını tespit motoruna (detect/)
iletir ("tap"), böylece hem meşru hem de saldırı trafiği gözlemlenebilir.

Köprü, komutların MAVLink içeriğini ANLAMAYA çalışmaz ve kendi başına imza
üretmez: imzalama uçtan uca GCS <-> drone arasında yapılır (bkz.
common/signing.py, bridge/legit_gcs_demo.py, sim/drone_sim.py). Böylece
köprünün kendisi ele geçirilse bile sahte komutlar drone tarafında reddedilir.

--enforce bayrağı verilirse köprü, bariz imzasız/bozuk zarfları drone'a
iletmeden erkenden eler (performans/bonus katmanı) — ama bu, drone'daki asıl
yetkilendirme kontrolünün YERİNE geçmez, onu TAMAMLAR.

Kullanım:
  python3 bridge/bridge.py
  python3 bridge/bridge.py --enforce --secret-file secrets/mavlink.key
"""
import argparse
import socket
import sys
import time
from pathlib import Path

from pymavlink.dialects.v20 import common as mavlink2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import events as ev  # noqa: E402
from common import signing as sig  # noqa: E402


def _hostport(s: str):
    host, port = s.rsplit(":", 1)
    return host, int(port)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drone-telemetry-in", default="127.0.0.1:14560",
                     help="drone'un telemetri gönderdiği adres (burada dinlenir)")
    ap.add_argument("--drone-cmd-out", default="127.0.0.1:14561",
                     help="drone'un komut dinlediği adres (komutlar buraya iletilir)")
    ap.add_argument("--gcs-cmd-in", default="127.0.0.1:14565",
                     help="GCS/saldırganın komut gönderdiği adres (burada dinlenir)")
    ap.add_argument("--tap", default="127.0.0.1:14600",
                     help="tespit motorunun dinlediği adres")
    ap.add_argument("--no-tap", action="store_true")
    ap.add_argument("--secret-file", default=None,
                     help="--enforce ile birlikte erken reddetme için kullanılır")
    ap.add_argument("--enforce", action="store_true",
                     help="imzasız/bozuk komutları drone'a iletmeden köprüde ele")
    args = ap.parse_args()

    telem_host, telem_port = _hostport(args.drone_telemetry_in)
    cmd_out_addr = _hostport(args.drone_cmd_out)
    gcs_host, gcs_port = _hostport(args.gcs_cmd_in)
    tap_addr = None if args.no_tap else _hostport(args.tap)

    telem_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    telem_sock.bind((telem_host, telem_port))
    telem_sock.setblocking(False)

    gcs_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gcs_sock.bind((gcs_host, gcs_port))
    gcs_sock.setblocking(False)

    fwd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tap_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if tap_addr else None

    telem_parser = mavlink2.MAVLink(None)
    telem_parser.robust_parsing = True

    secret = None
    if args.enforce:
        if not args.secret_file:
            print("[bridge] UYARI: --enforce verildi ama --secret-file yok; "
                  "erken eleme devre dışı.")
        else:
            secret = sig.load_or_create_key(args.secret_file)

    def emit_tap(kind, **kw):
        if not tap_sock:
            return
        try:
            evt = ev.TapEvent(src="bridge", kind=kind, **kw)
            tap_sock.sendto(evt.to_json(), tap_addr)
        except OSError:
            pass

    print(f"[bridge] telemetri dinleniyor : {args.drone_telemetry_in}")
    print(f"[bridge] GCS komut girişi     : {args.gcs_cmd_in} -> drone {args.drone_cmd_out}")
    print(f"[bridge] erken eleme (enforce): {'AÇIK' if secret else 'kapalı'}")
    print(f"[bridge] tap                  : {'kapalı' if not tap_sock else args.tap}")

    while True:
        did_work = False

        # Köprü, gerçek drone ile olası bir "drone taklit eden" saldırganın
        # (bkz. attacks/spoof_gps.py) paketlerini AYNI telli ortamda görür —
        # tıpkı gerçek bir telsiz/radyo bağlantısındaki gibi. Bu yüzden burada
        # içeriği gerçekten ayrıştırıyoruz: GLOBAL_POSITION_INT bulunursa
        # "telemetry" olayı (konumla birlikte) üretiyoruz, böylece
        # detect/rules.py'deki gps_jump kuralı sahte konumu da görebilir.
        try:
            data, peer = telem_sock.recvfrom(4096)
            did_work = True
            peer_s = f"{peer[0]}:{peer[1]}"
            try:
                msgs = telem_parser.parse_buffer(data) or []
            except Exception:
                msgs = []
            tagged = False
            for msg in msgs:
                if msg.get_type() == "GLOBAL_POSITION_INT":
                    emit_tap(
                        "telemetry", peer=peer_s, local_port=telem_port,
                        sysid=msg.get_srcSystem(), compid=msg.get_srcComponent(),
                        msg_type="GLOBAL_POSITION_INT",
                        data={"lat": msg.lat / 1e7, "lon": msg.lon / 1e7,
                              "alt": msg.relative_alt / 1000.0},
                    )
                    tagged = True
            if not tagged:
                emit_tap("telemetry_relay", peer=peer_s, local_port=telem_port,
                         data={"bytes": len(data)})
        except BlockingIOError:
            pass

        try:
            data, peer = gcs_sock.recvfrom(4096)
            did_work = True
            peer_s = f"{peer[0]}:{peer[1]}"
            verified = None
            if secret is not None:
                _, reason = sig.verify_envelope(secret, data)
                verified = reason == "ok"
                if not verified:
                    emit_tap("command_blocked", peer=peer_s, local_port=gcs_port,
                             verified=False, data={"reason": reason})
                    print(f"[bridge] ENGELLENDİ ({reason}) <- {peer_s}")
                    data = None  # drone'a iletme
            if data is not None:
                emit_tap("command_relay", peer=peer_s, local_port=gcs_port,
                         verified=verified, data={"bytes": len(data)})
                fwd_sock.sendto(data, cmd_out_addr)
        except BlockingIOError:
            pass

        if not did_work:
            time.sleep(0.005)


if __name__ == "__main__":
    main()
