"""Link budget in the Deep-Space-Network style: work in P/N0 (dB-Hz).

    P_rx  = P_tx + G_tx - L_feed_tx - L_path + G_rx
    N0    = k * T_sys            T_sys = T_sky + T_rx (from noise figure)
    P/N0  = P_rx - N0
    SNR(2500 Hz) = P/N0 - 34.0   (the yardstick WSJT-X and Uranus quote)

This makes the trade explicit: a mode with threshold S (dB in 2500 Hz)
needs P/N0 >= S + 34. URC-60 at -30.8 dB needs only ~3 dB-Hz.
"""

import math

K_DBW = -228.6                   # Boltzmann constant, dBW/K/Hz

# Rough quiet-site sky + man-made noise temperatures (K). Urban sites can be
# 3-10x higher on 2 m. On 2 m the sky dominates, so a cryogenic LNA buys
# nothing; on 70 cm a 0.3-0.5 dB NF preamp at the antenna matters.
SKY_K = {144: 400.0, 432: 60.0}

THRESHOLDS = {                   # 50 % decode, dB in 2500 Hz
    "FT8": -21.0, "WSPR": -31.4, "FST4-60": -28.1, "FST4W-120": -32.8,
    "UR-15": -19.4, "UR-60": -25.4, "URC-15": -24.7, "URC-60": -30.8, "URC-120": -33.8,
}


def fspl_db(freq_mhz, dist_km):
    return 32.45 + 20 * math.log10(freq_mhz) + 20 * math.log10(dist_km)


def nf_to_k(nf_db):
    return 290.0 * (10 ** (nf_db / 10) - 1)


def budget(tx_w, freq_mhz, dist_km, tx_gain_dbi=0.0, rx_gain_dbi=0.0, feed_loss_db=1.0,
           extra_path_loss_db=0.0, rx_nf_db=1.0, sky_k=None):
    band = 144 if freq_mhz < 300 else 432
    t_sys = (SKY_K[band] if sky_k is None else sky_k) + nf_to_k(rx_nf_db)
    p_tx = 10 * math.log10(tx_w)
    loss = fspl_db(freq_mhz, dist_km) + extra_path_loss_db
    p_rx = p_tx + tx_gain_dbi - feed_loss_db - loss + rx_gain_dbi
    n0 = K_DBW + 10 * math.log10(t_sys)
    pn0 = p_rx - n0
    return {"eirp_dbw": p_tx + tx_gain_dbi - feed_loss_db, "path_loss_db": loss,
            "p_rx_dbw": p_rx, "t_sys_k": t_sys, "n0_dbw_hz": n0, "p_n0_dbhz": pn0,
            "snr2500_db": pn0 - 10 * math.log10(2500),
            "margins_db": {m: pn0 - 10 * math.log10(2500) - th for m, th in THRESHOLDS.items()}}


def voyager_example():
    """The worked Voyager-1 numbers: 23 W, 48 dBi, 8.4 GHz, one light-day, 70 m dish, 20 K."""
    d_km = 299792.458 * 86400
    p_tx = 10 * math.log10(23)
    pn0 = p_tx + 48 - fspl_db(8400, d_km) + 74 - (K_DBW + 10 * math.log10(20))
    return pn0, pn0 - 10 * math.log10(2500)
