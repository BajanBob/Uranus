import unittest

import numpy as np

import struct

from uranus import aprs, fec, geo, linkbudget, mapgen, pskreporter, scheduler, urcoherent, urmode, wsjt


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
        self.assertEqual(m, {"call": "8P6AB", "grid": "GK03", "type": 5, "value": 16383})

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


class TestURC(unittest.TestCase):
    def test_constant_envelope(self):
        from scipy.signal import hilbert
        y = urcoherent.modulate(urcoherent.message_to_symbols("K1ABC", "FN42"), "URC-15")
        e = np.abs(hilbert(y.astype(float)))[3000:-3000]
        self.assertLess(10 * np.log10(e.max() ** 2 / np.mean(e ** 2)), 0.3)

    def test_audio_loopback_weak(self):
        rng = np.random.default_rng(11)
        sym = urcoherent.message_to_symbols("K1ABC", "FN42", 2, 321)
        y = urcoherent.modulate(sym, "URC-15", f0=1500.3).astype(float)
        x = np.concatenate([np.zeros(15000), y, np.zeros(6000)])
        sigma = np.sqrt(np.mean(y ** 2) / (10 ** (-21 / 10) * 2500 * 2 / urcoherent.FS))
        x += sigma * rng.standard_normal(len(x))
        res = urcoherent.decode_audio(x, "URC-15", df_max=2.0)
        self.assertTrue(any(r["call"] == "K1ABC" and r["value"] == 321 for r in res))

    def test_noise_only(self):
        rng = np.random.default_rng(12)
        self.assertEqual(urcoherent.decode_audio(rng.standard_normal(20 * 12000), "URC-15"), [])


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
        sp = [{"call": "K1ABC", "grid": "FN42", "snr": -27.3, "freq_hz": 144491500, "mode": "URC", "time": 1_800_000_000}]
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
        self.assertIn(b"URC", pkt)


class TestMap(unittest.TestCase):
    def test_aggregate_and_render(self):
        st = mapgen.aggregate(mapgen.demo_spots(), "GK03ec")
        self.assertEqual(len(st), 11)                       # SAMPLE8 is on both bands
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
        urc = scheduler.Slot("2m", "urc", 144.49, submode="URC-60")
        self.assertEqual(scheduler.align(1000.0, urc) % 60, 1.0)

    def test_order_and_gaps(self):
        cfg = {"timing": {"gap_between_tx_s": 60, "gap_between_bands_s": 180}}
        slots = [scheduler.Slot("2m", "aprs", 144.39), scheduler.Slot("2m", "ft8", 144.174),
                 scheduler.Slot("2m", "wspr", 144.49), scheduler.Slot("70cm", "aprs", 432.8)]
        ev = scheduler.plan(cfg, slots, 0.0)
        self.assertEqual([e[2].mode for e in ev], ["aprs", "ft8", "wspr", "aprs"])
        self.assertGreaterEqual(ev[1][0] - ev[0][1], 60)
        self.assertGreaterEqual(ev[3][0] - ev[2][1], 180)


if __name__ == "__main__":
    unittest.main()
