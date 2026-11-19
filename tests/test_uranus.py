import os
import sys
import tomllib
import time
import unittest

import numpy as np

import struct

from uranus import aprs, cucumber, fec, geo, linkbudget, mapgen, pskreporter, scheduler, pumpkin, urmode, wsjt


class TestFEC(unittest.TestCase):
    def test_crc16_ccitt_false_vector(self):
        bits = [int(b) for c in b"123456789" for b in format(c, "08b")]
        self.assertEqual(fec.crc16(bits), 0x29B1)

    def test_viterbi_noiseless(self):
        rng = np.random.default_rng(0)
        bits = rng.integers(0, 2, 80)
        coded = fec.conv_encode(bits)
        self.assertEqual(len(coded), 264)
        llr = 4.0 * (1 - 2 * coded)
        self.assertTrue(np.array_equal(fec.viterbi_decode(llr, 80), bits))


class TestURMode(unittest.TestCase):
    def test_pack_roundtrip(self):
        m = urmode.unpack_message(urmode.pack_message("8P6AB", "GK03", 5, 16383))
        self.assertEqual(m, {"kind": "beacon", "call": "8P6AB", "grid": "GK03", "type": 5, "value": 16383})

    def test_tones(self):
        t = urmode.message_to_tones("K1ABC", "FN42")
        self.assertEqual(len(t), 164)
        self.assertTrue(np.array_equal(t[urmode.SYNC_POS], urmode.SYNC_TONES))

    def test_audio_loopback_weak(self):
        rng = np.random.default_rng(3)
        y = urmode.modulate(urmode.message_to_tones("K1ABC", "FN42", 1, 77), "UR-15", f0=1100)
        x = np.concatenate([np.zeros(9000), y, np.zeros(6000)]).astype(float)
        sigma = np.sqrt(np.mean(y ** 2) / (10 ** (-17 / 10) * 2500 * 2 / urmode.FS))
        x += sigma * rng.standard_normal(len(x))
        res = urmode.decode_audio(x, "UR-15")
        self.assertTrue(any(r["call"] == "K1ABC" and r["value"] == 77 for r in res))

    def test_noise_only_no_false_decode(self):
        rng = np.random.default_rng(4)
        self.assertEqual(urmode.decode_audio(rng.standard_normal(20 * urmode.FS), "UR-15"), [])


class TestPumpkin(unittest.TestCase):
    def test_constant_envelope(self):
        from scipy.signal import hilbert
        y = pumpkin.modulate(pumpkin.message_to_symbols("K1ABC", "FN42"), "PUMPKIN-15")
        e = np.abs(hilbert(y.astype(float)))[3000:-3000]
        self.assertLess(10 * np.log10(e.max() ** 2 / np.mean(e ** 2)), 0.3)

    def test_audio_loopback_weak(self):
        rng = np.random.default_rng(11)
        sym = pumpkin.message_to_symbols("K1ABC", "FN42", 2, 321)
        y = pumpkin.modulate(sym, "PUMPKIN-15", f0=1500.3).astype(float)
        x = np.concatenate([np.zeros(15000), y, np.zeros(6000)])
        sigma = np.sqrt(np.mean(y ** 2) / (10 ** (-21 / 10) * 2500 * 2 / pumpkin.FS))
        x += sigma * rng.standard_normal(len(x))
        res = pumpkin.decode_audio(x, "PUMPKIN-15", df_max=2.0)
        self.assertTrue(any(r["call"] == "K1ABC" and r["value"] == 321 for r in res))

    def test_noise_only(self):
        rng = np.random.default_rng(12)
        self.assertEqual(pumpkin.decode_audio(rng.standard_normal(20 * 12000), "PUMPKIN-15"), [])


class TestCucumber(unittest.TestCase):
    def test_fm_link_below_voice_threshold(self):
        rng = np.random.default_rng(21)
        sym = cucumber.message_to_symbols("8P5AB", "GK03", 3, 999)
        y = cucumber.modulate(sym, "CUCUMBER-15").astype(float)
        a = np.concatenate([np.zeros(15000), y, np.zeros(6000)])
        x = cucumber.fm_channel(a, -6.0, rng)          # 16 dB below where FM voice is readable
        res = cucumber.decode_audio(x, "CUCUMBER-15")
        self.assertTrue(any(r["call"] == "8P5AB" and r["value"] == 999 for r in res))
        self.assertNotIn("fade_db", res[0])

    def test_legacy_urc_names(self):
        import tomllib
        t = open("config/uranus.toml", encoding="utf-8").read()
        t = t.replace('mode = "pumpkin"\n  submode = "PUMPKIN-60"\n  freq_mhz = 144.490\n  enabled = false',
                      'mode = "urc"\n  submode = "URC-60"\n  freq_mhz = 144.490\n  enabled = true', 1)
        import os, tempfile
        fd, path = tempfile.mkstemp(suffix=".toml")
        os.write(fd, t.replace("N0CALL", "8P5AB").encode())
        os.close(fd)
        _, slots = scheduler.load_config(path)
        os.unlink(path)
        s = [x for x in slots if x.freq_mhz == 144.49 and x.enabled and x.mode != "wspr"][0]
        self.assertEqual((s.mode, s.submode), ("pumpkin", "PUMPKIN-60"))


class TestChat(unittest.TestCase):
    def test_text_frames_roundtrip(self):
        from uranus import urmode as u
        for text, seq, more in [("DUCT OPEN", 0, False), ("QSL 73 ", 3, True), ("+-./? 0Z", 4, True)]:
            m = u.unpack_message(u.pack_text(text, seq, more))
            self.assertEqual((m["kind"], m["text"].rstrip(), m["seq"], m["more"]), ("text", text.rstrip(), seq, more))
        b = u.unpack_message(u.pack_message("8P5AB", "GK03", 6, 0))
        self.assertEqual(b["kind"], "beacon")

    def test_reassembly_keeps_spaces_and_sender(self):
        from uranus import chat, urmode as u
        frames = chat.frames_for("Hello world from Barbados, QSL?", "8P5AB", "GK03", True)
        self.assertTrue(frames[0][0].startswith("ID"))
        re_ = chat.Reassembler()
        msgs = []
        for _, bits in frames:
            for e in re_.feed(u.unpack_message(bits)):
                if e["type"] == "message":
                    msgs.append(e)
        self.assertEqual(msgs[0]["text"], "HELLO WORLD FROM BARBADOS. QSL?")
        self.assertEqual(msgs[0]["from"], "8P5AB")

    def test_chat_over_cucumber(self):
        from uranus import chat
        ev = chat.demo("CQ 220 DE 8P5AB", "CUCUMBER-15", -6.0, seed=4)
        self.assertIn("CQ 220 DE 8P5AB", [e["text"] for e in ev if e["type"] == "message"])


class TestLinkBudget(unittest.TestCase):
    def test_fspl(self):
        self.assertAlmostEqual(linkbudget.fspl_db(144, 100), 115.6, delta=0.1)

    def test_example_budget(self):
        b = linkbudget.example()
        self.assertAlmostEqual(b["snr2500_db"], b["p_n0_dbhz"] - 33.98, delta=0.01)
        self.assertLess(b["path_loss_db"], 230)


class TestGeo(unittest.TestCase):
    def test_grid_roundtrip(self):
        self.assertEqual(geo.latlon_to_grid(13.1, -59.6), "GK03ec")
        lat, lon = geo.grid_to_latlon("GK03ec")
        self.assertAlmostEqual(lat, 13.1, delta=0.05)
        self.assertAlmostEqual(lon, -59.6, delta=0.05)

    def test_distance(self):
        # Barbados to St Lucia is about 170 km
        self.assertAlmostEqual(geo.distance_km((13.1, -59.6), (13.9, -61.0)), 170, delta=10)


class TestPSKReporter(unittest.TestCase):
    def test_ipfix_structure(self):
        sp = [{"call": "K1ABC", "grid": "FN42", "snr": -27.3, "freq_hz": 144491500, "mode": "PUMPKIN", "time": 1_800_000_000}]
        pkt = pskreporter.build_packet("8P5AB", "GK03ec", sp, 0, 1234)
        ver, length = struct.unpack(">HH", pkt[:4])
        self.assertEqual((ver, length), (10, len(pkt)))
        pos, sets = 16, []
        while pos < len(pkt):
            sid, slen = struct.unpack(">HH", pkt[pos:pos + 4])
            self.assertEqual(slen % 4, 0)
            sets.append(sid)
            pos += slen
        self.assertEqual(pos, len(pkt))
        self.assertEqual(sets, [3, 2, 0x9992, 0x9993])
        self.assertIn(b"PUMPKIN", pkt)


class TestMap(unittest.TestCase):
    def test_aggregate_and_render(self):
        st = mapgen.aggregate(mapgen.demo_spots(), "GK03ec")
        self.assertEqual(len(st), 14)                       # SAMPLE8 is on both 2 m and 70 cm
        self.assertIn("1.25m", {s["band"] for s in st})
        self.assertEqual({s["band"] for s in st if s["call"] == "SAMPLE8"}, {"2m", "70cm"})
        for s in st:
            self.assertAlmostEqual(sum(s["prop"].values()), 1.0, delta=0.01)
        both = [s for s in st if s["call"] == "SAMPLE3"][0]
        self.assertEqual(both["dirs"], ["heard", "rx"])
        self.assertTrue(both["online"])
        html = mapgen.render(st, "8P5AB", "GK03ec", note=mapgen.DEMO_NOTE)
        self.assertIn("SAMPLE DATA", html)
        self.assertNotIn("__DATA__", html)


class TestPropagation(unittest.TestCase):
    def test_textbook_cases(self):
        from uranus import propagation as pr
        bb = (13.1, -59.6)
        noon_june = 1_781_000_000 - (1_781_000_000 % 86400) + 16 * 3600   # ~12h local, June
        es = pr.classify(bb, (25.0, -77.4), "2m", noon_june, snr=-8)
        self.assertEqual(es[0][0], "es")
        es70 = pr.classify(bb, (25.0, -77.4), "70cm", noon_june, snr=-8)
        self.assertNotEqual(es70[0][0], "es")
        evening = noon_june + 8 * 3600
        tep = pr.classify(bb, (-23.5, -46.6), "2m", evening, snr=-15, fade_db=7, spread_hz=0.9)
        self.assertEqual(tep[0][0], "tep")
        duct = pr.classify(bb, (10.5, -66.9), "70cm", evening, snr=-12, fade_db=0.7, spread_hz=0.02, steady=1.0)
        self.assertEqual(duct[0][0], "ducting")
        near = pr.classify(bb, (13.15, -59.55), "2m", noon_june)
        self.assertEqual(near[0][0], "los")


class TestBandsRadiosSDR(unittest.TestCase):
    def test_band_of(self):
        from uranus import propagation as pr
        self.assertEqual(pr.band_of(144_490_000), "2m")
        self.assertEqual(pr.band_of(222_130_000), "1.25m")
        self.assertEqual(pr.band_of(432_300_000), "70cm")

    def test_transverter_offset(self):
        s = scheduler.Slot("1.25m", "pumpkin", 222.130, lo_mhz=194.0)
        self.assertAlmostEqual(s.rig_hz, 28.130e6, delta=1)

    def test_config_editor_keeps_disabled_slots(self):
        import tomllib
        from uranus import radios
        t = open("config/uranus.toml", encoding="utf-8").read()
        t2 = radios.set_band_active(t, "1.25m", True)
        t2 = radios.set_toml_key(t2, "receive", "source", "rtl_fm")
        c = tomllib.loads(t2)
        self.assertTrue([b for b in c["band"] if b["name"] == "1.25m"][0]["active"])
        self.assertEqual(c["receive"]["source"], "rtl_fm")
        self.assertFalse([sl for b in c["band"] for sl in b["slot"] if sl["freq_mhz"] == 144.8][0]["enabled"])

    def test_profiles(self):
        from uranus import radios
        names = [p.name for p in radios.PROFILES]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(any("1.25m" in p.bands for p in radios.PROFILES))
        for p in radios.PROFILES:
            self.assertIn(p.backend, ("hamlib", "hackrf", "rtl_fm", "audio-only"))
            self.assertTrue(p.help())

    def test_usb_codec_dropdown_and_lookup(self):
        from uranus import audiodev as a
        devs = [{"index": 1, "name": "Speakers (Realtek Audio)", "hostapi": "MME", "inputs": 0, "outputs": 2},
                {"index": 7, "name": "Speakers (USB Audio CODEC )", "hostapi": "Windows WASAPI", "inputs": 0,
                 "outputs": 2},
                {"index": 2, "name": "Speakers (USB Audio CODEC )", "hostapi": "MME", "inputs": 0, "outputs": 2},
                {"index": 3, "name": "Microphone (USB Audio CODEC )", "hostapi": "MME", "inputs": 2, "outputs": 0}]
        out = a.choices("out", devs)
        self.assertTrue(out[0].startswith("Speakers (USB Audio CODEC") and a.CODEC_TAG in out[0])
        self.assertEqual(len([c for c in out if "CODEC" in c]), 1)           # listed once
        spec = a.spec_from_label(out[0])
        self.assertEqual(a.resolve(spec, "out", devs), 2)                     # MME preferred
        self.assertEqual(a.resolve("USB Audio CODEC", "in", devs), 3)
        self.assertEqual(a.resolve("4", "out", devs), 4)
        self.assertIsNone(a.resolve("default", "out", devs))
        none = a.choices("out", [])
        self.assertEqual(a.spec_from_label(none[0]), "USB Audio CODEC")      # offered before plug-in
        with self.assertRaises(RuntimeError):
            a.resolve("USB Audio CODEC", "out", devs[:1])
        self.assertIn("Icom IC-9100", [p.name for p in __import__("uranus.radios").radios.PROFILES])

    @unittest.skipIf(os.name == "nt", "uses shell-script stand-ins for Hamlib")
    def test_plug_and_play_rigctld(self):
        """ensure() finds Hamlib, looks up the IC-9100 model, picks the CP210x port, starts rigctld
        and reads the frequency, all without a model number in the settings."""
        import socket
        import tempfile
        import textwrap
        from uranus import rigctl
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "rigctl"), "w") as f:
            f.write("#!/bin/sh\necho ' Rig #  Mfg    Model     Version'\n"
                    "echo '  3068  Icom   IC-9100   20220909.0  Stable  RIG_MODEL_IC9100'\n"
                    "echo '  3081  Icom   IC-9700   20230109.0  Stable  RIG_MODEL_IC9700'\n")
        srv = textwrap.dedent(f"""
            import socket, sys
            args = sys.argv[1:]
            open({os.path.join(d, 'args')!r}, 'w').write(' '.join(args))
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', int(args[args.index('-t') + 1]))); s.listen()
            while True:
                c, _ = s.accept(); f = c.makefile('rw')
                for line in f:
                    f.write('144300000\\n' if line.strip() == 'f' else 'RPRT 0\\n'); f.flush()
                c.close()
            """)
        with open(os.path.join(d, "fake_rigctld.py"), "w") as f:
            f.write(srv)
        with open(os.path.join(d, "rigctld"), "w") as f:
            f.write(f"#!/bin/sh\nexec {sys.executable} {os.path.join(d, 'fake_rigctld.py')} \"$@\"\n")
        for n in ("rigctl", "rigctld"):
            os.chmod(os.path.join(d, n), 0o755)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            tport = s.getsockname()[1]
        os.environ["URANUS_HAMLIB_DIR"] = d
        try:
            self.assertEqual(rigctl.model_for("IC-9100"), 3068)
            ports = [("COM4", "Bluetooth link"), ("COM3", "Silicon Labs CP210x USB to UART Bridge (COM3)")]
            self.assertEqual(rigctl.detect_port("", ports), "COM3")
            self.assertEqual(rigctl.detect_port("COM4", ports), "COM4")
            orig = rigctl.detect_port
            rigctl.detect_port = lambda pref="", ports=None: orig(pref, [("/dev/ttyUSB0", "CP2102 USB to UART")])
            try:
                msg = rigctl.ensure({"radio": {"profile": "Icom IC-9100", "rigctld_port": tport, "cat_baud": 19200}})
            finally:
                rigctl.detect_port = orig
            self.assertIn("144.3000 MHz", msg)
            self.assertEqual(open(os.path.join(d, "args")).read().split()[:6],
                             ["-m", "3068", "-r", "/dev/ttyUSB0", "-s", "19200"])
        finally:
            rigctl.stop()
            del os.environ["URANUS_HAMLIB_DIR"]

    def test_frequency_plan_inside_itu_allocations(self):
        from uranus import freqplan as fp
        for f in fp.PLAN:
            msg = fp.check(f.band, f.mode, f.mhz, f.region if f.region != "All" else "R2")
            if f.band == "60m":
                self.assertNotIn("outside", msg, f)            # 60 m always reminds about national rules
            else:
                self.assertEqual(msg, "", f)
            self.assertTrue(fp.segment(f.band, f.mhz), f)
        for band in fp.BAND_EDGES:
            self.assertTrue(fp.options(band, "ft8"), band)
            if band not in fp.HF_BANDS:
                self.assertTrue(fp.options(band, "pumpkin"), band)
            if band not in ("60m", "1.25m"):
                self.assertTrue(fp.options(band, "wspr") or band == "60m", band)
        self.assertIn("outside", fp.check("2m", "aprs", 148.0))
        cfg = tomllib.load(open("config/uranus.toml", "rb"))
        for band in cfg["band"]:                          # every default slot can be saved from its dropdown
            for sl in band["slot"]:
                cur = fp.find(band["name"], sl["mode"], sl["freq_mhz"])
                mhz = float((cur.label() if cur else fp.fmt(sl["freq_mhz"])).split()[0])
                self.assertNotIn("outside", fp.check(band["name"], sl["mode"], mhz), (band["name"], sl))
        for f in fp.PLAN:                                 # labels keep every digit, so saving round-trips
            self.assertAlmostEqual(float(f.label().split()[0]), f.mhz, places=6, msg=f.label())
        self.assertIn("Region 2 only", fp.check("1.25m", "pumpkin", 222.13, "R1"))
        wspr = fp.find("2m", "wspr", 144.489)
        pk = fp.find("2m", "pumpkin", 144.490)
        self.assertGreater((pk.mhz + 0.0015) - (wspr.mhz + 0.0016), 0.0005)   # Pumpkin tones clear of WSPR

    def test_aprs_receiver_decodes_noisy_deemphasised_packet(self):
        from scipy.signal import lfilter
        from uranus import aprs, aprs_rx
        fs, rng = 12000, np.random.default_rng(7)
        y = aprs.packet_audio("8P5AB-11", aprs.position_info(13.1, -59.6, comment="test"), fs=fs)
        k = np.exp(-2 * np.pi * 300 / fs)
        y = lfilter([1 - k], [1, -k], y)                    # FM receiver de-emphasis
        y = y / np.std(y)
        x = np.concatenate([rng.normal(0, 1, 8000), y + rng.normal(0, 10 ** (-10 / 20), len(y)), rng.normal(0, 1, 8000)])
        frames = aprs_rx.decode_audio(0.2 * x, fs)
        self.assertEqual(len(frames), 1)
        pkt = aprs_rx.parse_frame(frames[0])
        self.assertEqual(pkt["source"], "8P5AB-11")
        lat, lon = aprs_rx.position(pkt)
        self.assertAlmostEqual(lat, 13.1, places=2)
        self.assertAlmostEqual(lon, -59.6, places=2)
        self.assertEqual(aprs_rx.decode_audio(rng.normal(0, 1, 120000), fs), [])   # noise alone: nothing
        lat, lon = aprs_rx._compressed_pos("/5L!!<*e7>7P[")                  # APRS spec example
        self.assertAlmostEqual(lat, 49.5, places=3)
        self.assertAlmostEqual(lon, -72.75, places=3)

    def test_ft8_message_parsing(self):
        p = wsjt.parse_ft8_message
        self.assertEqual(p("CQ K1ABC FN42"), ("K1ABC", "FN42"))
        self.assertEqual(p("CQ DX 8P5AB GK03"), ("8P5AB", "GK03"))
        self.assertEqual(p("K1ABC W9XYZ EN37"), ("W9XYZ", "EN37"))
        self.assertEqual(p("K1ABC W9XYZ RR73"), ("W9XYZ", ""))
        m = wsjt._FT8_LINE.match("000000 -12  0.2 1234 ~  CQ K1ABC FN42")
        self.assertEqual(m.group(5), "CQ K1ABC FN42")

    def test_hamlib_uses_data_mode_with_fallback(self):
        from uranus.radio import HamlibRadio
        r = HamlibRadio.__new__(HamlibRadio)
        sent = []

        def cmd(text, refuse=()):
            sent.append(text)
            if text.split()[0] == "M" and text.split()[1] in refuse:
                raise RuntimeError("RPRT -11")
            return "RPRT 0"
        r.data_mode, r._cmd = True, cmd
        r.tune(144_174_000, "USB")
        r.tune(144_390_000, "FM")
        self.assertEqual(sent, ["F 144174000", "M PKTUSB 0", "F 144390000", "M PKTFM 0"])
        sent.clear()
        r._cmd = lambda t: cmd(t, refuse=("PKTUSB",))
        r.tune(144_174_000, "USB")                             # rig without data modes: plain USB
        self.assertEqual(sent, ["F 144174000", "M PKTUSB 0", "M USB 0"])
        sent.clear()
        r.data_mode, r._cmd = False, cmd
        r.tune(144_174_000, "USB")
        self.assertEqual(sent, ["F 144174000", "M USB 0"])

    @staticmethod
    def _fake_rig(swr_reading):
        import threading
        import time as _t
        from uranus.radio import HamlibRadio
        r = HamlibRadio.__new__(HamlibRadio)
        r.max_swr, r.swr_poll_s, r.last_swr, r._swr_warned = 2.0, 0.1, None, False
        r._lock, r.ptt_lead_s, r.max_tx_s = threading.Lock(), 0.0, 320
        r.sent, keyed = [], threading.Event()

        def cmd(text):
            r.sent.append((round(_t.time(), 2), text))
            if text == "T 1":
                keyed.set()
            elif text == "T 0":
                keyed.clear()
            elif text == "l SWR":
                v = swr_reading()
                if v is None:
                    raise RuntimeError("RPRT -11")
                return str(v)
            return "RPRT 0"

        def player(path, audio, fs, dur):
            end = _t.time() + dur
            while _t.time() < end and keyed.is_set():          # stops when PTT is dropped
                _t.sleep(0.02)
        r._cmd, r.player = cmd, player
        return r

    def test_swr_guard_drops_ptt(self):
        import time as _t
        from uranus.radio import SWRError
        r = self._fake_rig(lambda: 3.4)
        t0 = _t.time()
        with self.assertRaises(SWRError) as ctx:
            r.transmit(14_074_000, "USB", np.zeros(12000 * 5, np.float32), 12000, "ft8")
        self.assertLess(_t.time() - t0, 2.0)                   # cut within about a second, not after 5 s
        self.assertAlmostEqual(ctx.exception.swr, 3.4)
        self.assertEqual(r.sent[-1][1], "T 0")

    def test_swr_guard_passes_good_match_and_silent_rigs(self):
        r = self._fake_rig(lambda: 1.3)
        r.transmit(14_074_000, "USB", np.zeros(12000, np.float32), 12000, "ft8")
        self.assertAlmostEqual(r.last_swr, 1.3)
        r = self._fake_rig(lambda: None)                       # rig can't report SWR: transmit anyway
        r.transmit(14_074_000, "USB", np.zeros(12000, np.float32), 12000, "ft8")
        self.assertIsNone(r.last_swr)
        r = self._fake_rig(lambda: 9.9)
        r.max_swr = 0                                          # check switched off
        r.transmit(14_074_000, "USB", np.zeros(6000, np.float32), 12000, "ft8")
        self.assertNotIn("l SWR", [c for _, c in r.sent])

    def test_runner_blocks_band_after_swr_trip(self):
        import tempfile
        from uranus.radio import SWRError
        t = open("config/uranus.toml", encoding="utf-8").read().replace('callsign = "N0CALL"', 'callsign = "8P5AB"', 1)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(t)
        cfg, slots = scheduler.load_config(f.name)

        class Rig:
            def tune(self, hz, mode):
                pass

            def transmit(self, *a):
                raise SWRError(2.8, 2.0, "ft8")
        r = scheduler.Runner(cfg, slots, Rig())
        ev = []
        r.on_event = ev.append
        r._sleep_until = lambda t: None
        r.audio_for = lambda s: (np.zeros(10), 12000)
        s = next(x for x in slots if x.mode == "ft8")
        r._one(s, scheduler.RIG_MODE_DEFAULT, {}, s.band)
        self.assertEqual([e["type"] for e in ev], ["tx_start", "swr_trip", "tx_end"])
        self.assertIn(s.band, r.blocked)

    def test_radio_from_config(self):
        from uranus.radio import HamlibRadio
        import unittest.mock as um
        with um.patch("socket.create_connection"), um.patch("uranus.radio._pick_player"):
            r = HamlibRadio.from_config({"rigctld_port": 4532, "max_tx_s": 320, "data_mode": True, "max_swr": 2.5})
        self.assertEqual((r.max_swr, r.max_tx_s, r.data_mode), (2.5, 320, True))
        with um.patch("socket.create_connection"), um.patch("uranus.radio._pick_player"):
            self.assertEqual(HamlibRadio.from_config({}).max_swr, 2.0)

    def test_timetable_windows_example(self):
        from uranus import timetable as tt
        t = tt.settings({"timetable": {"enabled": True, "clock": "utc", "windows": tt.EXAMPLE}})
        day = 1_700_006_400                                    # 00:00 UTC
        self.assertEqual(time.gmtime(day).tm_hour, 0)
        H = 3600
        w, act, end = tt.at(t, day + 1 * H + 1)
        self.assertEqual((w.text(), act, end), ("01:00-06:00 transmit 3", "transmit", day + 6 * H))
        ticks = tt.ticks(w, day + 1 * H, end, t)
        self.assertEqual(len(ticks), 100)                      # 20 an hour for 5 hours
        self.assertEqual(ticks[:2], [day + H, day + H + 180])
        self.assertEqual(tt.at(t, day + 6.5 * H)[1:], ("listen", day + 7 * H))      # outside: listen
        self.assertEqual(tt.at(t, day + 8 * H)[1:], ("listen", day + 9 * H))
        self.assertEqual(tt.at(t, day + 9 * H + 60)[1:], ("listen", day + 9 * H + 180))  # 09:00-09:03 gap
        w, act, end = tt.at(t, day + 10 * H + 100)              # 10:01:40
        self.assertEqual((act, end), ("transmit", day + 22 * H))
        first = tt.ticks(w, day + 10 * H + 100, end, t)[0]
        self.assertEqual(first, day + 10 * H + 180)             # 10:03:00 - on the 09:03 + 3 min grid
        self.assertEqual(tt.at(t, day + 23 * H)[1:], ("listen", day + 23 * H + 59 * 60))
        t2 = tt.settings({"timetable": {"enabled": True, "clock": "utc", "outside": "pause",
                                        "windows": ["22:00-02:00 transmit 5"]}})
        self.assertEqual(tt.at(t2, day + 1 * H)[1:], ("transmit", day + 2 * H))  # across midnight
        self.assertEqual(tt.at(t2, day + 3 * H)[1:], ("pause", day + 22 * H))
        with self.assertRaises(ValueError):
            tt.parse("25:00-26:00 listen")
        self.assertEqual(tt.overlaps([tt.parse("01:00-03:00 listen"), tt.parse("02:00-04:00 pause")]),
                         [("01:00-03:00 listen", "02:00-04:00 pause")])

    def test_session_transmits_on_the_grid_and_listens_between(self):
        from uranus import clock, timetable as tt
        clock.set_offset(0.0)
        fake_now = [1_700_006_400 + 9 * 3600 + 3 * 60 - 30.0]   # 09:02:30 UTC
        events, sent = [], []

        cfg = {"station": {"callsign": "8P5AB", "grid": "GK03"}, "receive": {"dial_mhz": 14.074, "mode": "ft8"},
               "timetable": {"enabled": True, "clock": "utc", "windows": ["09:03-09:12 transmit 3"]}}
        sess = scheduler.Session.__new__(scheduler.Session)
        sess.cfg, sess.radio, sess.tt = cfg, None, tt.settings(cfg)
        sess.on_event, sess.reporter, sess.listen_in_gaps, sess._k = events.append, None, True, 0
        slot = type("S", (), {"band": "20m", "enabled": True, "mode": "ft8", "label": "ft8 14.074"})()
        sess.slots = [slot]

        class R:
            blocked = {}
            stop = __import__("threading").Event()

            def _sleep_until(self, t):
                fake_now[0] = max(fake_now[0], t)

            def _one(self, s, rigmodes, cs, band):
                sent.append(round(fake_now[0] + 5))
                fake_now[0] += 15

            def _gap(self, s, until):
                fake_now[0] = max(fake_now[0], until)
        sess.runner = R()
        sess.stop = sess.runner.stop
        real = clock.now
        clock.now = lambda: fake_now[0]
        try:
            w, _, end = tt.at(sess.tt, fake_now[0] + 31)
            sess._transmit(w, end)
        finally:
            clock.now = real
        base = 1_700_006_400 + 9 * 3600
        self.assertEqual(sent, [base + 180, base + 360, base + 540])   # 09:03, 09:06, 09:09
        self.assertIn({"type": "next_tx", "at": base + 360}, events)

    def test_ntp_query_math(self):
        from uranus import clock
        import unittest.mock as um
        import struct as st
        real = time.time()

        def ntp(t):
            sec = int(t) + 2208988800
            return st.pack("!II", sec, int((t % 1) * 2 ** 32))
        reply = bytes([0x24, 2]) + bytes(30) + ntp(real + 2.0) + ntp(real + 2.0)   # server 2 s ahead
        sock = um.MagicMock()
        sock.__enter__.return_value.recvfrom.return_value = (reply, None)
        with um.patch("socket.socket", return_value=sock):
            off, rtt = clock.query("x")
        self.assertAlmostEqual(off, 2.0, delta=0.05)

    def test_map_has_builtin_world_and_no_tile_service(self):
        h = mapgen.render([], "8P5AB", "GK03ec")
        self.assertIn('id="world"', h)
        self.assertNotIn("__WORLD__", h)
        self.assertNotIn("cartocdn", h)
        self.assertNotIn("tile.openstreetmap.org", h)
        from uranus.worldmap import WORLD
        import json as _j
        w = _j.loads(WORLD)
        barbados = [p for p in w["coordinates"] if all(-59.7 < x < -59.4 and 13.0 < y < 13.4 for x, y in p[0])]
        self.assertTrue(barbados)                              # small islands kept

    def test_noise_filter_learns_whistles_blanks_clicks_spares_signals(self):
        from uranus.noisefilter import NoiseFilter
        rng = np.random.default_rng(5)
        fs, n = 12000, 12000 * 15
        t = np.arange(n) / fs
        nf = NoiseFilter(fs)

        def slot(k, clicks=False):
            x = rng.standard_normal(n) + 4 * np.sin(2 * np.pi * 1180 * t)              # charger whistle
            x += 4 * np.sin(2 * np.pi * (700 + 300 * (k % 2)) * t) * (t < 12.6)       # FT8-like, moves
            if clicks:
                for i in range(0, n - 20, 100):
                    x[i:i + 4] += 30
            return x
        for k in range(4):
            nf.clean(slot(k))
        self.assertTrue(any(abs(h - 1180) < 6 for h in nf.stats["line_hz"]), nf.stats)
        self.assertFalse(any(abs(h - 700) < 6 or abs(h - 1000) < 6 for h in nf.stats["line_hz"]), nf.stats)
        y = nf.clean(slot(4, clicks=True))
        self.assertGreater(nf.stats["blanked_pct"], 1.0)
        spec = np.abs(np.fft.rfft(y))
        f = np.fft.rfftfreq(n, 1 / fs)
        sig = spec[np.abs(f - 700) < 2].max()
        whistle = spec[np.abs(f - 1180) < 2].max()
        floor = spec[np.abs(f - 1300) < 2].max()
        self.assertLess(whistle, 2 * floor)                      # whistle down to the noise floor
        self.assertGreater(sig, 4 * whistle)                     # signal kept
        quiet = NoiseFilter(fs)
        z = rng.standard_normal(n)
        out = quiet.clean(z)
        self.assertEqual(quiet.stats["blanked_pct"], 0.0)
        self.assertGreater(np.corrcoef(out[3000:-3000], z[3000:-3000])[0, 1], 0.95)   # plain noise untouched

    def test_hf_band_and_classification(self):
        from uranus import propagation as pr
        self.assertEqual(pr.band_of(14_075_000), "20m")
        self.assertEqual(pr.band_of(144_174_000), "2m")
        home, de = geo.grid_to_latlon("GK03gc"), geo.grid_to_latlon("JN48")
        r = pr.classify(home, de, "20m", 1_763_262_000)
        self.assertEqual(r[0][0], "f2")                          # never "tropospheric ducting" on HF
        self.assertNotIn("ducting", [k for k, p, _ in r if p > 0])
        r2 = pr.classify(home, geo.grid_to_latlon("FK96"), "2m", 1_763_262_000)
        self.assertIn(r2[0][0], ("ducting", "tropo_scatter", "los", "aircraft"))

    def test_sanity_flags_false_decodes(self):
        from uranus import sanity
        self.assertIn("Antarctica", sanity.suspect("2K5GEQ", "BB16"))
        self.assertIn("ocean", sanity.suspect("Z65ZEB", "HL55"))
        self.assertIn("?", sanity.suspect("PY5DC", "GG54", "? a1"))
        for c, g in (("D44JB", "HK77"), ("8P5AB", "GK03"), ("5R8IC", "LH43"), ("XQ5BRC", "FF33"), ("VP8PJ", "GD18")):
            self.assertEqual(sanity.suspect(c, g), "", c)
        m = wsjt._FT8_LINE.match("000000 -22  0.3 1234 ~  CQ PY5DC GG54           ? a1")
        msg = m.group(5).strip()
        fm = wsjt._FLAGS.search(msg)
        self.assertEqual((msg[:fm.start()].rstrip(), fm.group(0).strip()), ("CQ PY5DC GG54", "? a1"))

    def test_octopus_report(self):
        import tempfile
        from uranus import octopus
        d = tempfile.mkdtemp()
        csvp = os.path.join(d, "t.csv")
        with open(csvp, "w") as f:
            f.write("call,grid,snr,best,freq_hz,mode,time,direction\n"
                    "DL8WEM,JN48,-17,-15,14075000,FT8,1763262000,rx\n"
                    "2K5GEQ,BB16,-24,-24,14075000,FT8,1763262000,rx\n"
                    "J69DS,FK93,-12,-8,144174000,FT8,1763262000,rx\n")
        path, rows = octopus.run("GK03gc", csv_path=csvp, day="2026-11-16", root=d)
        t = open(path).read()
        self.assertIn("## 2 m and 70 cm", t)
        self.assertIn("J69DS", t.split("## HF")[0])               # 2 m station listed in the focus section
        self.assertIn("2K5GEQ", t.split("## Anomalies")[1])
        self.assertIn("F2-layer skywave", t)

    def test_gui_colour_table_complete(self):
        import ast
        import re as _re
        src = open("uranus/gui.py", encoding="utf-8").read()
        i = src.index("C = {")
        table = ast.literal_eval(src[i + 4:src.index("}", i) + 1])
        used = set(_re.findall(r'C\["(\w+)"\]', src))
        self.assertFalse(used - set(table), f"colours used but not defined: {used - set(table)}")

    def test_hidden_watermark_html_pdf_and_map(self):
        import tempfile
        from uranus import watermark as wm
        h = wm.stamp_html("<html><head><title>x</title></head><body><p>hi</p></body></html>")
        self.assertTrue(wm.is_marked_html(h))
        self.assertEqual(wm.stamp_html(h), h)                  # only once
        self.assertIn('content="Kammie M Holder FSS, LUTCF, MBLAS"', h)
        self.assertTrue(wm.is_marked_html(mapgen.render([], "8P5AB", "GK03ec")))
        try:
            from pypdf import PdfReader
            from reportlab.pdfgen import canvas
        except ImportError:
            return                                             # PDF tools not installed (CI): HTML checked above
        d = tempfile.mkdtemp()
        src = os.path.join(d, "a.pdf")
        c = canvas.Canvas(src)
        c.drawString(72, 720, "Uranus")
        c.save()
        wm.stamp_pdf(src)
        r = PdfReader(src)
        self.assertEqual(r.metadata["/Author"], wm.OWNER)
        self.assertIn(wm.OWNER, r.pages[0].extract_text())
        self.assertIn("Uranus", r.pages[0].extract_text())
        self.assertTrue(wm.is_marked_pdf(src))

    def test_aprs_iss_frequency_uses_ariss_path(self):
        from scipy.signal import resample_poly
        from uranus import aprs_rx
        import tempfile
        t = open("config/uranus.toml", encoding="utf-8").read().replace('callsign = "N0CALL"', 'callsign = "8P5AB"', 1)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(t)
        cfg, slots = scheduler.load_config(f.name)
        r = scheduler.Runner(cfg, slots, None)
        for mhz, path in ((145.825, ["ARISS"]), (144.390, ["WIDE1-1"])):
            a, fs = r.audio_for(scheduler.Slot("2m", "aprs", mhz))
            pkt = aprs_rx.parse_frame(aprs_rx.decode_audio(resample_poly(a, 1, 4), 12000)[0])
            self.assertEqual(pkt["path"], path)

    def test_beacon_decodes_aprs_between_transmissions(self):
        import tempfile
        import time as _t
        from uranus import aprs, monitor
        t = open("config/uranus.toml", encoding="utf-8").read().replace('callsign = "N0CALL"', 'callsign = "8P5AB"', 1)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(t)
        cfg, slots = scheduler.load_config(f.name)

        class Rig:                                   # any real-radio class (not DryRunRadio)
            pass
        r = scheduler.Runner(cfg, slots, Rig())
        events = []
        r.listen_in_gaps, r.on_event = True, events.append
        pkt = aprs.packet_audio("W1ABC-9", aprs.position_info(42.36, -71.06), fs=12000)
        orig = monitor.record
        monitor.record = lambda sec, device="default", fs=12000: np.concatenate(
            [np.zeros(6000), pkt, np.zeros(max(0, int(sec * fs) - 6000 - len(pkt)))])[:int(sec * fs)]
        try:
            r._gap(scheduler.Slot("2m", "aprs", 144.390), _t.time() + 9)
        finally:
            monitor.record = orig
        calls = [e["spot"]["call"] for e in events if e["type"] == "decode"]
        self.assertEqual(calls, ["W1ABC-9"])
        self.assertEqual(events[-1]["type"], "gap_end")

    def test_hf_aprs_300_baud_on_usb(self):
        import tempfile
        from scipy.signal import resample_poly
        from uranus import aprs_rx
        t = open("config/uranus.toml", encoding="utf-8").read().replace('callsign = "N0CALL"', 'callsign = "8P5AB"', 1)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(t)
        cfg, slots = scheduler.load_config(f.name)
        r = scheduler.Runner(cfg, slots, None)
        hf = scheduler.Slot("30m", "aprs", 10.1476)
        self.assertEqual(scheduler.rig_mode(hf, scheduler.RIG_MODE_DEFAULT), "USB")
        self.assertEqual(scheduler.rig_mode(scheduler.Slot("2m", "aprs", 144.39), scheduler.RIG_MODE_DEFAULT), "FM")
        a, fs = r.audio_for(hf)
        x = resample_poly(a, 1, 4)
        self.assertEqual(aprs_rx.decode_audio(x, 12000), [])               # not 1200-baud VHF APRS
        pkt = aprs_rx.parse_frame(aprs_rx.decode_audio(x, 12000, hf=True)[0])
        self.assertEqual((pkt["source"], pkt["path"]), ("8P5AB-11", []))     # no digipeater path on HF

    def _sig_place(self, sig, start_s, total_s, snr_db, rng):
        fs = 12000
        x = np.zeros(int(total_s * fs))
        s0 = int(start_s * fs)
        n = min(len(sig), len(x) - s0)
        x[s0:s0 + n] = sig[:n]
        x = x / np.sqrt(np.mean(sig ** 2)) * np.sqrt(2500 / 6000) * 10 ** (snr_db / 20)
        return x + rng.normal(0, 1, len(x))

    def test_signal_identification_by_signature(self):
        from uranus import aprs, signalid as sid
        rng, fs = np.random.default_rng(11), 12000
        t0 = 1_700_000_040.0                                  # a 120-second boundary (WSPR) and 15 s (FT8)
        def gfsk(n, sp, baud, f0, M, costas=None):
            tones = rng.integers(0, M, n)
            if costas is not None:
                for st in (0, 36, 72):
                    tones[st:st + 7] = costas
            return wsjt.gfsk(tones, int(fs / baud), sp, f0, bt=2.0)
        sym = pumpkin.message_to_symbols("8P5AB", "GK03")
        t = np.arange(12 * fs) / fs
        key = np.zeros_like(t)
        pos = 0.5
        for el in [1, 3, 1, 1, 3, 3, 1, 1, 1, 3, 1, 3, 3, 1]:
            key[int(pos * fs):int((pos + el * 0.08) * fs)] = 1
            pos += el * 0.08 + 0.08
        bits = rng.integers(0, 2, int(10 * 45.45))
        rtty = np.sin(2 * np.pi * np.cumsum(np.repeat(np.where(bits, 2125, 2295), int(fs / 45.45))) / fs)
        cases = {
            "FT8": (gfsk(79, 6.25, 6.25, 1200, 8, [3, 1, 4, 0, 6, 5, 2]), 0.5, 15, -12, t0),
            "WSPR": (gfsk(162, 1.4648, 1.4648, 1500, 4), 1.0, 120, -18, t0),
            "PUMPKIN-15": (pumpkin.modulate(sym, "PUMPKIN-15"), 1.0, 15, -5, t0),
            "PUMPKIN-60": (pumpkin.modulate(sym, "PUMPKIN-60"), 1.0, 60, -14, t0),
            "UR-15": (urmode.modulate(urmode.message_to_tones("8P5AB", "GK03"), "UR-15"), 1.0, 15, -5, t0),
            "CW": (np.sin(2 * np.pi * 700 * t) * np.convolve(key, np.ones(48) / 48, "same"), 0, 12, 0, None),
            "Carrier": (np.sin(2 * np.pi * 1000 * t), 0, 12, -5, None),
            "RTTY": (rtty, 1, 12, 5, None),
            "APRS / packet 1200": (aprs.packet_audio("8P5AB", aprs.position_info(13.1, -59.6), fs=fs), 2, 8, 10, None),
        }
        for want, (sig, start, total, snr, tt) in cases.items():
            ds = sid.identify(self._sig_place(sig, start, total, snr, rng), t0=tt)
            self.assertTrue(ds, want)
            self.assertEqual(ds[0].mode, want, [(d.mode, d.confidence, d.reasons) for d in ds])
            self.assertTrue(ds[0].reasons)
        for _ in range(3):                                       # noise alone: nothing identified
            self.assertEqual([d.mode for d in sid.identify(rng.normal(0, 1, 15 * fs), t0=t0) if d.mode != "Unknown"], [])
        mem = sid.Memory()                                       # the same signal again gains confidence
        x = self._sig_place(cases["FT8"][0], 0.5, 15, -12, rng)
        c1 = mem.update(sid.identify(x, t0=t0), now=1000)[0].confidence
        d2 = mem.update(sid.identify(x, t0=t0), now=1015)[0]
        self.assertGreater(d2.confidence, c1)
        self.assertEqual(d2.seen, 2)

    def test_auto_mode_identifies_and_decodes_aprs(self):
        import tempfile
        from uranus import aprs, monitor
        t = open("config/uranus.toml", encoding="utf-8").read().replace('callsign = "N0CALL"', 'callsign = "8P5AB"', 1)
        cfg = tomllib.loads(t)
        cfg["receive"] = {"mode": "auto", "dial_mhz": 144.390}
        events = []
        lis = monitor.Listener(cfg, spot_path=tempfile.mktemp(), on_event=events.append)
        pkt = aprs.packet_audio("W1ABC-9", aprs.position_info(42.36, -71.06), fs=12000)
        orig = monitor.record
        monitor.record = lambda sec, device="default", fs=12000: np.concatenate(
            [np.random.default_rng(2).normal(0, 0.01, 24000), pkt,
             np.random.default_rng(3).normal(0, 0.01, int(sec * fs))])[:int(sec * fs)]
        import time as _t
        real_time = _t.time
        try:
            base = (real_time() // 15 + 1) * 15
            _t.time = lambda: base                              # pretend we are at a slot boundary
            lis.run(slots=1)
        finally:
            _t.time = real_time
            monitor.record = orig
        idents = [i["mode"] for e in events if e["type"] == "identified" for i in e["items"]]
        self.assertIn("APRS / packet 1200", idents)
        self.assertIn("W1ABC-9", [e["spot"]["call"] for e in events if e["type"] == "decode"])

    def test_ft4_slots_and_frequencies(self):
        from uranus import freqplan as fp
        s = scheduler.Slot("20m", "ft4", 14.080)
        self.assertEqual(scheduler.align(1_700_000_000.2, s) % 7.5, 0.5)
        self.assertAlmostEqual(scheduler.slot_duration(s), 5.04)
        self.assertEqual(scheduler.rig_mode(s, scheduler.RIG_MODE_DEFAULT), "USB")
        want = {"80m": 3.575, "40m": 7.0475, "30m": 10.140, "20m": 14.080, "17m": 18.104, "15m": 21.140,
                "12m": 24.919, "10m": 28.180, "6m": 50.318, "2m": 144.170}
        for band, mhz in want.items():
            f = fp.find(band, "ft4", mhz)
            self.assertIsNotNone(f, band)
            self.assertEqual(fp.check(band, "ft4", mhz), "", band)

    def test_pskreporter_live_status(self):
        from uranus import pskreporter
        r = pskreporter.Reporter("8P5AB", "GK03", test=True)
        r.stop.set()
        r.add({"call": "K4XYZ", "grid": "EM73", "snr": -21, "freq_hz": 144491500, "mode": "PUMPKIN",
               "time": 1_700_000_000})
        r.add({"call": "K4XYZ", "grid": "EM73", "snr": -20, "freq_hz": 144491500, "mode": "PUMPKIN",
               "time": 1_700_000_010})                                        # same minute: once
        s = r.status()
        self.assertEqual((s["server"], s["queued"], s["added"], s["sent"]), ("test", 1, 1, 0))

    def test_hackrf_iq_is_upper_sideband(self):
        from uranus import sdr
        fs = 12000
        a = 0.5 * np.sin(2 * np.pi * 1500 * np.arange(fs) / fs)
        iq = np.frombuffer(b"".join(sdr.iq_chunks(a, fs, "USB", 2_400_000, 200_000)), np.int8).astype(float)
        z = iq[0::2] + 1j * iq[1::2]
        seg = z[600_000:600_000 + 2 ** 20]
        spec = np.abs(np.fft.fft(seg * np.hanning(len(seg)))) ** 2
        f = np.fft.fftfreq(len(seg), 1 / 2_400_000)
        self.assertAlmostEqual(f[np.argmax(spec)], 201_500, delta=10)


class TestAPRS(unittest.TestCase):
    def test_fcs_vector(self):
        self.assertEqual(aprs.crc_x25(b"123456789"), 0x906E)

    def test_afsk_roundtrip(self):
        info = aprs.position_info(13.1, -59.6, comment="test")
        audio = aprs.packet_audio("8P6AB-11", info)
        frames = aprs.demod_check(audio)
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].endswith(info.encode()))

    def test_position_format(self):
        self.assertEqual(aprs.position_info(13.1, -59.6), "!1306.00N/05936.00W-")


class TestWSJT(unittest.TestCase):
    def test_parse_wspr_style(self):
        txt = "Message: K1ABC FN42 37\nChannel symbols:\n" + " ".join(["1", "3"] * 81) + "\n"
        self.assertEqual(len(wsjt.parse_tones(txt, 162, 3)), 162)


class TestScheduler(unittest.TestCase):
    def test_align(self):
        ft8 = scheduler.Slot("2m", "ft8", 144.174)
        wspr = scheduler.Slot("2m", "wspr", 144.49)
        self.assertEqual(scheduler.align(1000.0, ft8), 1005.5)
        self.assertEqual(scheduler.align(1000.0, wspr) % 120, 1.0)
        pk = scheduler.Slot("2m", "pumpkin", 144.49, submode="PUMPKIN-60")
        self.assertEqual(scheduler.align(1000.0, pk) % 60, 1.0)

    def test_order_and_gaps(self):
        cfg = {"timing": {"gap_between_tx_s": 60, "gap_between_bands_s": 180}}
        slots = [scheduler.Slot("2m", "aprs", 144.39), scheduler.Slot("2m", "ft8", 144.174),
                 scheduler.Slot("2m", "wspr", 144.49), scheduler.Slot("70cm", "aprs", 432.8)]
        ev = scheduler.plan(cfg, slots, 0.0)
        self.assertEqual([e[2].mode for e in ev], ["aprs", "ft8", "wspr", "aprs"])
        self.assertGreaterEqual(ev[1][0] - ev[0][1], 60)
        self.assertGreaterEqual(ev[3][0] - ev[2][1], 180)


class TestRecursion(unittest.TestCase):
    """Recursive SQL in spotdb (slot series, openings) and the recursive Maidenhead tree."""

    T0 = 1_763_000_040.0  # a WSPR slot boundary (multiple of 120 s)

    def spot(self, call, k, band_hz=14_095_600, snr=-10, grid="IO91"):
        return {"time": self.T0 + k * 120 + 5, "call": call, "grid": grid, "snr": snr, "freq_hz": band_hz,
                "mode": "WSPR", "direction": "rx"}

    def test_timeline_reports_quiet_slots(self):
        from uranus import spotdb
        db = spotdb.from_spots([self.spot("G4ABC", 0), self.spot("F5XYZ", 0), self.spot("G4ABC", 3)])
        rows = spotdb.timeline(db, self.T0, self.T0 + 5 * 120)
        self.assertEqual([r["spots"] for r in rows], [2, 0, 0, 1, 0])
        self.assertEqual(rows[0]["stations"], 2)

    def test_openings_split_on_long_gaps(self):
        from uranus import spotdb
        ks = [0, 1, 3, 4, 10, 11]  # gap of one slot stays open; gap of five ends it
        spots = [self.spot("G4ABC" if k % 2 else "EA8ZZ", k, snr=-k) for k in ks]
        spots.append(self.spot("W1AW", 2, band_hz=144_489_000))  # 2 m spot must not merge into 20 m
        db = spotdb.from_spots(spots)
        rows = spotdb.openings(db, "20m", self.T0, self.T0 + 12 * 120, max_gap=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["start"], rows[0]["stop"]), (self.T0, self.T0 + 5 * 120))
        self.assertEqual(rows[0]["spots"], 4)
        self.assertEqual(rows[0]["stations"], 2)
        self.assertEqual(rows[1]["spots"], 2)
        self.assertEqual(len(spotdb.openings(db, "2m", self.T0, self.T0 + 12 * 120)), 1)

    def test_slot_limit_is_enforced(self):
        from uranus import spotdb
        db = spotdb.from_spots([])
        with self.assertRaises(ValueError):
            spotdb.timeline(db, 0, 10 ** 9, 1)

    def test_import_is_incremental(self):
        import json
        import tempfile
        from uranus import spotdb
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "spots.jsonl")
            with open(log, "w") as f:
                f.write(json.dumps(self.spot("G4ABC", 0)) + "\n" + "not json\n")
            db = spotdb.connect(os.path.join(d, "spots.db"))
            self.assertEqual(spotdb.import_jsonl(db, log), 1)
            self.assertEqual(spotdb.import_jsonl(db, log), 0)
            with open(log, "a") as f:
                f.write(json.dumps(self.spot("F5XYZ", 1)) + "\n" + '{"time": 1, "call"')  # partial line
            self.assertEqual(spotdb.import_jsonl(db, log), 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM spots").fetchone()[0], 2)
            db.close()

    def test_grid_tree_nests_fields_squares_subsquares(self):
        tree = geo.grid_tree(["FK93mc", "fk93md", "FK93", "FK94", "IO91wm", "x"])
        self.assertEqual([n["grid"] for n in tree], ["FK", "IO"])
        fk = tree[0]
        self.assertEqual(fk["count"], 4)
        self.assertEqual(fk["children"][0], {"grid": "FK93", "count": 3, "children": [
            {"grid": "FK93mc", "count": 1, "children": []}, {"grid": "FK93md", "count": 1, "children": []}]})

    def test_octopus_report_includes_openings_and_fields(self):
        from uranus import octopus
        spots = [self.spot("G4ABC", k, grid="IO91") for k in (0, 1, 2)]
        spots += [self.spot("PY2XX", 1, grid="GG66", snr=-3)]
        rows = octopus.analyse(spots, "GK03ef")
        text = octopus.report(rows, "GK03ef", "2025-11-13", spots=spots)
        self.assertIn("## Band openings (UTC)", text)
        self.assertIn("| 20m |", text)
        self.assertIn("## Grid fields heard", text)
        self.assertIn("| IO | 1 | IO91 (1) |", text)


class TestDeepDecode(unittest.TestCase):
    def test_station_args_for_a_priori_decoding(self):
        from uranus import wsjt
        try:
            wsjt.set_station("8p5ab-10", "GK03ef")
            self.assertEqual(wsjt._station_args(), ["-c", "8P5AB", "-G", "GK03"])
            wsjt.set_station("N0CALL", "FN42")          # the placeholder call never goes to jt9
            self.assertEqual(wsjt._station_args(), [])
        finally:
            wsjt.set_station("", "")

    def test_jt9_gets_our_call(self):
        from unittest import mock
        from uranus import wsjt
        seen = {}
        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return mock.Mock(stdout="")
        try:
            wsjt.set_station("8P5AB", "GK03")
            with mock.patch.object(wsjt, "decoder_path", return_value="jt9"), mock.patch.object(wsjt.subprocess, "run", fake_run):
                wsjt.ft8_decode(np.zeros(15 * wsjt.FS), 144_174_000)
            cmd = seen["cmd"]
            self.assertIn("-d", cmd); self.assertEqual(cmd[cmd.index("-d") + 1], "3")
            self.assertEqual(cmd[cmd.index("-c") + 1], "8P5AB")
            self.assertEqual(cmd[cmd.index("-G") + 1], "GK03")
        finally:
            wsjt.set_station("", "")


class TestQ65(unittest.TestCase):
    def test_q65_listener_uses_60_second_slots_and_jt9_q65(self):
        import tempfile
        from unittest import mock
        from uranus import monitor, wsjt
        t = open("config/uranus.toml", encoding="utf-8").read().replace('callsign = "N0CALL"', 'callsign = "8P5AB"', 1)
        cfg = tomllib.loads(t)
        cfg["receive"] = {"mode": "q65", "dial_mhz": 144.170}
        with mock.patch.object(wsjt, "decoder_path", return_value="jt9"):
            lis = monitor.Listener(cfg, spot_path=tempfile.mktemp())
        self.assertEqual((lis.submode, lis.period), ("Q65", 60))
        self.assertGreater(lis.frame_s + 4.5, 51)            # records the whole 51 s transmission
        seen = {}
        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return mock.Mock(stdout="0010 -27  0.1 1500 :  8P5AB K1ABC FN42                      q2\n")
        with mock.patch.object(wsjt, "decoder_path", return_value="jt9"), mock.patch.object(wsjt.subprocess, "run", fake_run):
            mode, res = lis.decode(np.zeros(58 * wsjt.FS))
        cmd = seen["cmd"]
        self.assertEqual(mode, "Q65")
        self.assertIn("-3", cmd); self.assertEqual(cmd[cmd.index("-p") + 1], "60"); self.assertEqual(cmd[cmd.index("-b") + 1], "A")
        self.assertEqual(cmd[cmd.index("-c") + 1], "8P5AB")
        self.assertEqual(res[0]["message"], "8P5AB K1ABC FN42")   # the q2 marker is split off as a flag
        self.assertEqual((res[0]["call"], res[0]["grid"], res[0]["flags"], res[0]["freq_hz"]), ("K1ABC", "FN42", "q2", 144171500))
        wsjt.set_station("", "")


class TestQ65Transmit(unittest.TestCase):
    def test_q65_slot_timing_and_plan(self):
        from uranus import freqplan
        q = scheduler.Slot("2m", "q65", 144.170)
        self.assertEqual(scheduler.align(1000.0, q) % 60, 1.0)      # 1 s into the minute, like WSJT-X
        self.assertEqual(scheduler.slot_duration(q), 51.0)
        self.assertEqual(freqplan.check("2m", "q65", 144.170), "")
        self.assertTrue(freqplan.options("2m", "q65"))

    def test_wspr_off_the_standard_dial_is_flagged(self):
        from uranus import freqplan
        self.assertEqual(freqplan.wspr_dial("2m"), 144.489)
        self.assertIn("outside the 200 Hz WSPR window", freqplan.check("2m", "wspr", 144.490))
        self.assertEqual(freqplan.check("2m", "wspr", 144.489), "")
        self.assertEqual(freqplan.check("20m", "wspr", 14.0956), "")

    def test_default_settings_have_q65_off_and_wspr_on_the_standard_dial(self):
        cfg = tomllib.loads(open("config/uranus.toml", encoding="utf-8").read())
        b2 = next(b for b in cfg["band"] if b["name"] == "2m")
        q = [s for s in b2["slot"] if s["mode"] == "q65"]
        self.assertEqual(len(q), 1); self.assertFalse(q[0].get("enabled", True))
        self.assertEqual([s["freq_mhz"] for s in b2["slot"] if s["mode"] == "wspr"], [144.489])


class TestFaceplateTools(unittest.TestCase):
    def test_wefax_decodes_and_phases_a_chart(self):
        from uranus import wefax
        rng = np.random.default_rng(4)
        prof = np.linspace(0, 1, wefax.WIDTH)
        prof[:60] = 0
        img = np.tile(prof, (80, 1))
        x = np.concatenate([rng.normal(0, .3, int(3.37 * wefax.FS)), wefax.encode(img, f_err_hz=10)])
        rx = wefax.decode(x + rng.normal(0, 0.5, len(x)))
        self.assertEqual(len(rx.saved), 1)                      # start tone found, stop tone saved it
        out = rx.image().astype(float) / 255
        self.assertGreaterEqual(len(out), 76)
        self.assertLessEqual(len(out), 84)
        p = np.median(out, axis=0)
        self.assertGreater(np.corrcoef(p, prof)[0, 1], 0.98)    # phased: black margin at the left edge
        self.assertLess(p[:50].mean(), 0.15)

    def test_wefax_ignores_noise_and_dial_offset(self):
        from uranus import wefax
        rx = wefax.decode(np.random.default_rng(1).normal(0, 1, 60 * wefax.FS))
        self.assertEqual(rx.saved, [])
        self.assertEqual(rx.state, "idle")
        self.assertAlmostEqual(wefax.dial_mhz(8503.9), 8.502)
        self.assertTrue(any(s[1] == "NMG" and s[2] == 12789.9 for s in wefax.STATIONS))

    def test_scanner_dwells_on_activity_and_moves_on_when_quiet(self):
        from uranus import scanner
        chans = scanner.channels({"20m"}, {"ft8", "jt65"})
        self.assertEqual([(c.mode, c.mhz) for c in chans], [("ft8", 14.074), ("jt65", 14.076)])
        calls, events = [], []

        class FakeListener:
            def __init__(self, cfg, rep, on_event):
                self.cfg, self.ev = cfg, on_event

            def run(self, slots):
                rx = self.cfg["receive"]
                calls.append((rx["mode"], rx["dial_mhz"]))
                busy = rx["dial_mhz"] == 14.074 and len(calls) < 4
                self.ev({"type": "result", "count": 3 if busy else 0})
                if len(calls) > 8:
                    sc.halt()
        sc = scanner.Scanner({"receive": {}}, chans, on_event=events.append, tune=lambda ch: "tuned",
                             listener=FakeListener)
        sc.run()
        states = [(e["state"], e["mode"]) for e in events if e["type"] == "scan"]
        self.assertEqual(states[:3], [("probe", "ft8"), ("dwell", "ft8"), ("ended", "ft8")])
        self.assertIn(("quiet", "jt65"), states)
        self.assertEqual(calls[:2], [("auto", 14.074), ("ft8", 14.074)])   # probe with AUTO, dwell in FT8
        sc2 = scanner.Scanner({"receive": {}}, chans, tune=lambda ch: "", listener=FakeListener)
        sc2.current = chans[0]
        sc2.ignore()
        self.assertIn(chans[0].key, sc2.ignored)

    def test_my_frequencies_join_the_band_plan(self):
        import tempfile
        from uranus import freqplan, userfreqs
        cfgp = os.path.join(tempfile.mkdtemp(), "uranus.toml")
        self.assertEqual(userfreqs.add(cfgp, "ft8", 14.090, "club net"), "")
        self.assertIn("outside", userfreqs.add(cfgp, "ft8", 15.0))
        self.assertEqual(userfreqs.add(cfgp, "wefax", 4.3179, "NMG"), "")
        mine = [f for f in freqplan.PLAN if f.status == "mine"]
        self.assertEqual([(f.band, f.mode, f.mhz) for f in mine], [("20m", "ft8", 14.09)])
        self.assertEqual(freqplan.options("20m", "ft8")[0].status, "mine")
        userfreqs.remove(cfgp, "ft8", 14.090)
        self.assertFalse([f for f in freqplan.PLAN if f.status == "mine"])

    def test_pumpkin_ping_gives_both_stations_a_report(self):
        import tempfile
        from uranus import mapgen, ping
        self.assertEqual(ping.parse("PING K1ABC"), ("ping", "K1ABC", None))
        self.assertEqual(ping.parse("R-188P5AB"), ("report", "8P5AB", -18))
        self.assertEqual(ping.parse("RR+03K1ABC"), ("final", "K1ABC", 3))
        self.assertIsNone(ping.parse("HELLO THERE"))
        self.assertLessEqual(len(ping.report_text(-21, "K1ABCD", final=True)), 11)   # one chat frame
        d = tempfile.mkdtemp()
        air, evs = {"A": [], "B": []}, {"A": [], "B": []}
        a = ping.PingAgent("8P5AB", "GK03", air["A"].append, 144.495e6, "PUMPKIN-15", evs["A"].append,
                           os.path.join(d, "a.jsonl"))
        b = ping.PingAgent("K1ABC-7", "FN42", air["B"].append, 144.495e6, "PUMPKIN-15", evs["B"].append,
                           os.path.join(d, "b.jsonl"))

        def deliver(frm, call, grid, agent, snr):
            while air[frm]:
                agent.handle({"type": "id", "call": call, "grid": grid})
                agent.handle({"type": "message", "from": call, "text": air[frm].pop(0), "complete": True,
                              "snr": snr})
        a.ping("K1ABC")
        deliver("A", "8P5AB", "GK03", b, -18)
        self.assertEqual(air["B"], ["R-188P5AB"])
        deliver("B", "K1ABC", "FN42", a, -22)
        deliver("A", "8P5AB", "GK03", b, -18)
        ra = [e for e in evs["A"] if e["type"] == "report"][0]["contact"]
        rb = [e for e in evs["B"] if e["type"] == "report"][0]["contact"]
        self.assertEqual((ra["they_heard_me"], ra["i_heard_them"]), (-18, -22.0))
        self.assertEqual((rb["they_heard_me"], rb["i_heard_them"]), (-22, -18.0))
        self.assertTrue(3000 < ra["km"] < 4000 and ra["km"] == rb["km"])
        self.assertIn("TWO-WAY", ping.describe(ra))
        # a report nobody asked for is ignored
        a.handle({"type": "message", "from": "W9XYZ", "text": "R-108P5AB", "complete": True, "snr": -10})
        self.assertEqual(len([e for e in evs["A"] if e["type"] == "report"]), 1)
        # the map shows the contact as a smashed pumpkin
        contacts = ping.two_way(os.path.join(d, "a.jsonl"))
        st = mapgen.mark_contacts(mapgen.aggregate(mapgen.contact_spots(contacts), "GK03"), contacts)
        self.assertEqual([(x["call"], x["smashed"], x["dirs"]) for x in st], [("K1ABC", True, ["heard", "rx"])])
        self.assertIn("smashed", mapgen.render(st, "8P5AB", "GK03"))

    def test_pumpkin_ping_over_the_air_demo(self):
        from uranus import ping
        rep = [e for e in ping.demo(seed=1) if e["type"] == "report"]
        self.assertEqual(len(rep), 1)
        self.assertTrue(-24 <= rep[0]["contact"]["they_heard_me"] <= -12, rep[0]["contact"])

    def test_signal_id_names_signals_and_interference(self):
        from uranus import sigint, wefax
        fs, n = 12000, 15 * 12000
        t = np.arange(n) / fs
        rng = np.random.default_rng(3)

        def fsk(baud, shift=170.0):
            bits = rng.integers(0, 2, int(15 * baud) + 2)
            f = 1500 + shift / 2 * (2 * bits[(t * baud).astype(int)] - 1)
            return 0.6 * np.sin(2 * np.pi * np.cumsum(f) / fs)

        def top(x, dial=14.074e6):
            return [f.name for f in sigint.identify(x, dial_hz=dial, t0=0.0)]
        noise = lambda: rng.normal(0, 1, n)                     # noqa: E731
        self.assertEqual(top(noise()), ["Noise only"])
        hum = noise() + 1.5 * np.sin(2 * np.pi * 100 * t) + 0.8 * np.sin(2 * np.pi * 200 * t)
        self.assertEqual(top(hum)[0], "Mains hum")
        self.assertIn("50 Hz", " ".join(sigint.identify(hum)[0].reasons))
        self.assertEqual(top(fsk(45.45) + 0.5 * noise())[0], "RTTY")
        self.assertEqual(top(fsk(100) + 0.5 * noise())[0], "SITOR-B / NAVTEX")
        fx = wefax.encode(np.tile(np.linspace(0, 1, wefax.WIDTH), (60, 1)), start_s=0, stop_s=0)[6 * fs:6 * fs + n]
        self.assertEqual(top(2 * fx + 0.5 * noise())[0], "WEFAX")
        two = noise() + .5 * np.sin(2 * np.pi * 1000 * t) + .5 * np.sin(2 * np.pi * 1170 * t)
        self.assertNotIn("RTTY", top(two))                      # two carriers are not RTTY
        self.assertIn("NMG", sigint.context(8.502)[0])
        self.assertIn("WWV", sigint.context(10.0)[0])
        self.assertIn("What:", sigint.report(sigint.identify(hum), 14.074))

    def test_new_weak_signal_listen_modes(self):
        from uranus import freqplan, monitor, wsjt
        self.assertEqual(set(wsjt.DECODERS), {"ft8", "ft4", "q65", "jt65", "jt9", "fst4", "fst4w"})
        self.assertEqual([o.mhz for o in freqplan.options("20m", "jt65")], [14.076])
        self.assertIn("jt65", monitor.FOLLOW)
        m = wsjt._FT8_LINE.match("0001 -18  0.0 1500 `  K1JT K9AN EN50")
        self.assertIsNotNone(m)                                 # FST4 lines use a backtick marker

class TestRoadmapFeatures(unittest.TestCase):
    def test_mission_profiles_write_valid_settings(self):
        from uranus import profiles, radios
        t0 = open("config/uranus.toml", encoding="utf-8").read()
        for m in profiles.MISSIONS:
            t = t0
            for (sec, key), val in profiles.config_changes(m).items():
                t = radios.set_toml_key(t, sec, key, val)
            cfg = tomllib.loads(t)
            self.assertEqual(cfg["mission"]["name"], m.key)
            self.assertEqual(cfg["receive"]["submode"], m.receive["submode"])
            from uranus import timetable
            for w in cfg["timetable"].get("windows", []):
                timetable.parse(w)                               # every window is a valid timetable line
            self.assertTrue(m.changes())
        self.assertEqual(profiles.find("hurricane").key, "hurricane")
        self.assertEqual(profiles.find("Field day").key, "fieldday")
        self.assertIsNone(profiles.find("knitting"))

    def test_plain_english_commands(self):
        from uranus import commands
        p = commands.parse("listen on 2 m tonight and wake me for an opening", 14.074)
        self.assertEqual([a["do"] for a in p.actions], ["listen", "alert"])
        self.assertEqual((p.actions[0]["dial_mhz"], p.actions[0]["window"]), (144.174, "18:00-06:00"))
        p = commands.parse("beacon wspr every 10 minutes overnight")
        self.assertEqual(p.actions[0], {"do": "beacon", "every": 10, "window": "22:00-06:00", "mode": "wspr"})
        self.assertEqual(commands.parse("weather fax from Boston").actions[0]["call"], "NMF")
        self.assertEqual(commands.parse("scan 20 m and 40 m for jt65").actions[0],
                         {"do": "scan", "bands": ["20m", "40m"], "modes": ["jt65"]})
        self.assertEqual(commands.parse("listen for q65 on 144.170 from 7pm to 11pm").actions[0]["window"],
                         "19:00-23:00")
        self.assertEqual(commands.parse("hurricane watch").actions[0], {"do": "mission", "key": "hurricane"})
        self.assertEqual(commands.parse("ping k1abc").actions[0]["call"], "K1ABC")
        self.assertEqual(commands.parse("blah blah").actions, [])

    def test_best_band_follows_what_you_hear_and_the_sun(self):
        from uranus import bandadvisor
        now = 1_795_000_000
        sp = [{"time": now - 60 * i, "call": f"K{i}AA", "grid": "FN42", "freq_hz": 21_075_000, "direction": "rx"}
              for i in range(6)]
        r = bandadvisor.advise("GK03", spot_list=sp, sfi=150, kp=2, now=now, source="test")
        self.assertEqual(r["ranked"][0]["band"], "15m")
        self.assertIn("6 station(s)", r["ranked"][0]["reasons"][0])
        day, night = bandadvisor.muf(150, 60, 2), bandadvisor.muf(150, -30, 2)
        self.assertGreater(day, night)
        self.assertGreater(bandadvisor.muf(200, 60, 2), bandadvisor.muf(70, 60, 2))
        self.assertLess(bandadvisor.muf(150, 60, 8), day)
        self.assertGreater(bandadvisor.sun_elevation(13.1, -59.6, 1_795_000_000 - 1_795_000_000 % 86400 + 16 * 3600), 40)

    def test_signal_id_learns_per_frequency(self):
        import tempfile
        from uranus import siglib, sigint
        path = os.path.join(tempfile.mkdtemp(), "siglib.json")
        f = sigint.Finding("WEFAX", 0.7, 1900.0, 800.0, ["x"])
        for _ in range(3):
            siglib.teach(8.502, f, True, path=path)
        g = [sigint.Finding("WEFAX", 0.7, 1900.0, 800.0, ["x"]), sigint.Finding("RTTY", 0.6, 1920.0, 170.0, ["y"])]
        out = siglib.annotate(g, 8.502, path=path)
        self.assertGreater(out[0].confidence, 0.7)
        self.assertIn("usual here", out[0].reasons[0])
        rtty = [x for x in out if x.name == "RTTY"][0]
        self.assertTrue(rtty.new_here)
        siglib.teach(8.502, rtty, False, "WEFAX", path=path)
        self.assertLess(siglib.annotate([sigint.Finding("RTTY", 0.6, 1920.0, 170.0, [])], 8.502, path=path)[0]
                        .confidence, 0.6)
        self.assertEqual(siglib.usual(8.502, path=path)[0][0], "WEFAX")

    def test_interference_doctor_spots_the_cure(self):
        from uranus import doctor
        fs, n = 12000, 10 * 12000
        t = np.arange(n) / fs
        rng = np.random.default_rng(1)
        hum = doctor.measure(rng.normal(0, .02, n) + .05 * np.sin(2 * np.pi * 100 * t))
        clean = doctor.measure(rng.normal(0, .02, n))
        self.assertGreater(hum["hum_db"], 20)
        self.assertEqual(clean["hum_db"], 0)
        self.assertIn("hum", doctor.compare(hum, clean, "Laptop on battery"))
        v = doctor.verdict({"baseline": hum, "battery": clean, "antenna": hum})
        self.assertIn("Laptop on battery", v)

    def test_station_health_offline(self):
        from uranus import health
        cfg = tomllib.loads(open("config/uranus.toml", encoding="utf-8").read())
        res = health.check(cfg, cat=False, net=False, record=lambda sec, dev: np.full(36000, 1e-5))
        names = {r[0]: r for r in res}
        self.assertEqual(names["Callsign"][1], "fail")                  # N0CALL in the shipped settings
        self.assertEqual(names["Receive audio"][1], "warn")              # very low audio
        self.assertTrue(0 <= health.score(res) <= 100)

    def test_smart_beacon_backs_off_on_a_dead_band(self):
        from uranus import scheduler
        self.assertEqual([scheduler.smart_every(a) for a in (0, 1, 2, 3, 9)], [3, 2, 2, 1, 1])
        sp = [{"freq_hz": 14_075_000}, {"freq_hz": 14_076_000}, {"freq_hz": 144_490_000}]
        self.assertEqual(scheduler.band_activity("20m", spot_list=sp), 2)

    def test_network_paths_from_overheard_pings(self):
        import tempfile
        from uranus import mapgen, ping
        d = tempfile.mkdtemp()
        me = ping.PingAgent("8P5AB", "GK03", lambda t: None, 144.495e6, "PUMPKIN-15", None,
                            os.path.join(d, "contacts.jsonl"))
        me.handle({"type": "id", "call": "K1ABC", "grid": "FN42"})
        me.handle({"type": "id", "call": "W9XYZ", "grid": "EN37"})
        me.handle({"type": "message", "from": "W9XYZ", "text": "R-15K1ABC", "complete": True, "snr": -20})
        net = ping.network(os.path.join(d, "paths.jsonl"))
        self.assertEqual([(p["heard"], p["by"], p["snr"]) for p in net], [("K1ABC", "W9XYZ", -15)])
        self.assertIn('"net": [{"a": "K1ABC"', mapgen.render([], "8P5AB", "GK03", net=net))

    def test_wefax_autopilot_frequencies(self):
        from uranus import wefax
        self.assertEqual(wefax.pick("NMG", True), 17146.4)
        self.assertEqual(wefax.pick("NMG", False), 4317.9)
        self.assertEqual(wefax.next_frequency("NMG", 4317.9), 8503.9)
        self.assertEqual(wefax.next_frequency("NMG", 17146.4), 4317.9)


if __name__ == "__main__":
    unittest.main()
