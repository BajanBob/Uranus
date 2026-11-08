"""Uranus command line.

  python -m uranus plan                    show the transmit timeline
  python -m uranus run [--once]            run the beacon (dry-run or hamlib per config)
  python -m uranus aprs-wav out.wav        one APRS packet as audio
  python -m uranus ur-encode "CALL GRID [TYPE VALUE]" out.wav --submode UR-60
  python -m uranus ur-decode in.wav --submode UR-60 [--expect CALL GRID]
  python -m uranus ur-loopback --submode UR-15 --snr -18
  python -m uranus ur-sim                  sensitivity table for every submode
  python -m uranus urc-encode "CALL GRID [TYPE VALUE]" out.wav --submode URC-60
  python -m uranus urc-decode in.wav --submode URC-60 [--df-max 0.6] [--expect CALL GRID]
  python -m uranus urc-loopback --submode URC-15 --snr -23
  python -m uranus link-budget --watts 10 --mhz 144.49 --km 150 --tx-gain 10 --rx-gain 13
"""

import argparse
import datetime as dt
import logging
import time
import wave

import numpy as np

from . import aprs, linkbudget, scheduler, sim, urcoherent, urmode
from .radio import DryRunRadio, HamlibRadio, write_wav


def _read_wav(path):
    with wave.open(path) as w:
        fs, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(float) / 32768
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    if fs != urmode.FS:
        from scipy.signal import resample_poly
        g = np.gcd(fs, urmode.FS)
        x = resample_poly(x, urmode.FS // g, fs // g)
    return x


def main(argv=None):
    p = argparse.ArgumentParser(prog="uranus")
    p.add_argument("-c", "--config", default="config/uranus.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--cycles", type=int, default=1)
    a = sub.add_parser("run")
    a.add_argument("--once", action="store_true")
    a.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("aprs-wav")
    a.add_argument("out")
    a = sub.add_parser("ur-encode")
    a.add_argument("message")
    a.add_argument("out")
    a.add_argument("--submode", default="UR-60", choices=urmode.SUBMODES)
    a.add_argument("--f0", type=float, default=1500)
    a = sub.add_parser("ur-decode")
    a.add_argument("wav")
    a.add_argument("--submode", default="UR-60", choices=urmode.SUBMODES)
    a.add_argument("--expect", nargs=2, metavar=("CALL", "GRID"))
    a = sub.add_parser("ur-loopback")
    a.add_argument("--submode", default="UR-15", choices=urmode.SUBMODES)
    a.add_argument("--snr", type=float, default=-18)
    a = sub.add_parser("ur-sim")
    a.add_argument("--trials", type=int, default=150)
    a = sub.add_parser("urc-encode")
    a.add_argument("message")
    a.add_argument("out")
    a.add_argument("--submode", default="URC-60", choices=urcoherent.SUBMODES)
    a.add_argument("--f0", type=float, default=1500)
    a = sub.add_parser("urc-decode")
    a.add_argument("wav")
    a.add_argument("--submode", default="URC-60", choices=urcoherent.SUBMODES)
    a.add_argument("--f0", type=float, default=1500, help="nominal audio frequency")
    a.add_argument("--df-max", type=float, default=None, help="frequency search +/- Hz")
    a.add_argument("--expect", nargs=2, metavar=("CALL", "GRID"))
    a = sub.add_parser("urc-loopback")
    a.add_argument("--submode", default="URC-15", choices=urcoherent.SUBMODES)
    a.add_argument("--snr", type=float, default=-23)
    a.add_argument("--df", type=float, default=0.2, help="carrier error Hz")
    a = sub.add_parser("link-budget")
    a.add_argument("--watts", type=float, default=10)
    a.add_argument("--mhz", type=float, default=144.49)
    a.add_argument("--km", type=float, default=100)
    a.add_argument("--tx-gain", type=float, default=6.0)
    a.add_argument("--rx-gain", type=float, default=10.0)
    a.add_argument("--feed-loss", type=float, default=1.5)
    a.add_argument("--extra-loss", type=float, default=0.0,
                   help="beyond-horizon / obstruction loss above free space, dB")
    a.add_argument("--nf", type=float, default=1.0, help="receiver noise figure dB")
    a.add_argument("--sky-k", type=float, default=None)
    a.add_argument("--voyager", action="store_true", help="show the Voyager-1 example")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd in ("plan", "run", "aprs-wav"):
        cfg, slots = scheduler.load_config(args.config)

    if args.cmd == "plan":
        now = time.time()
        for b, e, s in scheduler.plan(cfg, slots, now, args.cycles):
            t = dt.datetime.fromtimestamp(b, dt.timezone.utc)
            print(f"{t:%H:%M:%S} UTC  +{(b - now) / 60:6.1f} min  {s.band:5} "
                  f"{s.label.split('_')[1]:7} {s.freq_mhz:9.3f} MHz  {e - b:6.1f} s")
    elif args.cmd == "run":
        rc = cfg["radio"]
        if args.dry_run or rc.get("backend", "dry-run") == "dry-run":
            radio = DryRunRadio()
        else:
            radio = HamlibRadio(rc["rigctld_host"], rc["rigctld_port"],
                                rc.get("audio_device", "default"), max_tx_s=rc.get("max_tx_s", 320))
        scheduler.Runner(cfg, slots, radio).run(cycles=1 if args.once else None)
    elif args.cmd == "aprs-wav":
        audio, fs = scheduler.Runner(cfg, slots, None).audio_for(
            next(s for s in slots if s.mode == "aprs"))
        write_wav(args.out, audio, fs)
        print(f"wrote {args.out}: {len(audio) / fs:.2f} s; self-check:",
              [f.split(b"\x03\xf0", 1)[1].decode("ascii") for f in aprs.demod_check(audio)] or "FAILED")
    elif args.cmd == "ur-encode":
        parts = args.message.split()
        tones = urmode.message_to_tones(parts[0], parts[1], *(int(x) for x in parts[2:4]))
        y = urmode.modulate(tones, args.submode, f0=args.f0)
        write_wav(args.out, y, urmode.FS)
        print(f"wrote {args.out}: {args.submode}, {len(y) / urmode.FS:.1f} s, "
              f"{4 / urmode.SUBMODES[args.submode]:.1f} Hz wide at {args.f0} Hz")
    elif args.cmd == "ur-decode":
        known = urmode.known_bits(*args.expect) if args.expect else None
        res = urmode.decode_audio(_read_wav(args.wav), args.submode, known=known)
        for r in res:
            print(f"SNR {r['snr']:6.1f} dB  dt {r['dt']:5.2f} s  f {r['freq']:7.1f} Hz  "
                  f"{r['call']} {r['grid']} type={r['type']} value={r['value']}")
        if not res:
            print("no decode")
    elif args.cmd == "ur-loopback":
        rng = np.random.default_rng()
        y = urmode.modulate(urmode.message_to_tones("8P6AB", "GK03", 1, 4242), args.submode, f0=1234)
        x = np.concatenate([np.zeros(urmode.FS), y, np.zeros(urmode.FS)]).astype(float)
        sigma = np.sqrt(np.mean(y ** 2) / (10 ** (args.snr / 10) * 2500 * 2 / urmode.FS))
        x += sigma * rng.standard_normal(len(x))
        print(urmode.decode_audio(x, args.submode) or "no decode")
    elif args.cmd == "urc-encode":
        parts = args.message.split()
        sym = urcoherent.message_to_symbols(parts[0], parts[1], *(int(x) for x in parts[2:4]))
        y = urcoherent.modulate(sym, args.submode, f0=args.f0)
        write_wav(args.out, y, urcoherent.FS)
        print(f"wrote {args.out}: {args.submode}, {len(y) / urcoherent.FS:.1f} s, MSK, "
              f"{1.5 / urcoherent.SUBMODES[args.submode]:.1f} Hz main lobe at {args.f0} Hz")
    elif args.cmd in ("urc-decode", "urc-loopback"):
        sub_ = args.submode
        dfm = args.df_max if getattr(args, "df_max", None) else 0.1 / urcoherent.SUBMODES[sub_]
        if args.cmd == "urc-decode":
            x = _read_wav(args.wav)
            known = urmode.known_bits(*args.expect) if args.expect else None
            res = urcoherent.decode_audio(x, sub_, f_nom=args.f0, df_max=dfm, known=known)
        else:
            rng = np.random.default_rng()
            sym = urcoherent.message_to_symbols("8P6AB", "GK03", 1, 4242)
            y = urcoherent.modulate(sym, sub_, f0=1500 + args.df).astype(float)
            x = np.concatenate([np.zeros(urcoherent.FS), y, np.zeros(urcoherent.FS)])
            sigma = np.sqrt(np.mean(y ** 2) / (10 ** (args.snr / 10) * 2500 * 2 / urcoherent.FS))
            x += sigma * rng.standard_normal(len(x))
            res = urcoherent.decode_audio(x, sub_, df_max=dfm)
        for r in res:
            print(f"SNR~{r['snr']:6.1f} dB  dt {r['dt']:5.2f} s  df {r['df']:+6.3f} Hz  "
                  f"{r['call']} {r['grid']} type={r['type']} value={r['value']}")
        if not res:
            print("no decode")
    elif args.cmd == "link-budget":
        if args.voyager:
            pn0, snr = linkbudget.voyager_example()
            print(f"Voyager 1 at one light-day: P/N0 = {pn0:.1f} dB-Hz, SNR(2500 Hz) = {snr:.1f} dB")
            return
        b = linkbudget.budget(args.watts, args.mhz, args.km, args.tx_gain, args.rx_gain,
                              args.feed_loss, args.extra_loss, args.nf, args.sky_k)
        print(f"EIRP {b['eirp_dbw']:.1f} dBW, path loss {b['path_loss_db']:.1f} dB, "
              f"Prx {b['p_rx_dbw']:.1f} dBW")
        print(f"Tsys {b['t_sys_k']:.0f} K -> N0 {b['n0_dbw_hz']:.1f} dBW/Hz; "
              f"P/N0 {b['p_n0_dbhz']:.1f} dB-Hz; SNR(2500 Hz) {b['snr2500_db']:.1f} dB")
        print("margin per mode (positive = should decode):")
        for m, v in b["margins_db"].items():
            print(f"  {m:10s} {v:+6.1f} dB")
    elif args.cmd == "ur-sim":
        es = np.arange(0.0, 6.1, 0.5)
        rows = {"plain": sim.ideal_sync_curve(es, args.trials),
                "a-priori call+grid": sim.ideal_sync_curve(es - 3, args.trials, ap=True),
                "4 repeats stacked": sim.ideal_sync_curve(es - 6, args.trials, repeats=4)}
        ths = {k: sim.threshold(es - {"plain": 0, "a-priori call+grid": 3,
                                      "4 repeats stacked": 6}[k], v) for k, v in rows.items()}
        print("50 % decode threshold, SNR in 2500 Hz, ideal sync (add ~0.6 dB for real sync)")
        print(f"{'submode':8} {'on air':>7} " + " ".join(f"{k:>20}" for k in ths))
        for sm, T in urmode.SUBMODES.items():
            print(f"{sm:8} {urmode.NSYM * T:6.1f}s " + " ".join(
                f"{urmode.snr2500_from_esn0(v, sm):20.1f}" for v in ths.values()))


if __name__ == "__main__":
    main()
