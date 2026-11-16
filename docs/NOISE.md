# Noise from the laptop charger (and other switch-mode supplies)

Uranus's **Noise filter** (main window, Receiver card) cleans each slot before decoding:

| Stage | Removes | How |
|---|---|---|
| Hum cut | 50/60 Hz hum and low harmonics | high-pass at 150 Hz |
| Line notcher | steady whistles / "birdies" | lines that stay on one frequency for 4 slots in a row are notched (about 9 Hz each, up to 24) |
| Impulse blanker | clicks, buzz, pulses | samples far above the running median level are zeroed for about 0.5 ms |

The console shows what it removed, e.g. `noise filter: blanked 4.2% clicks; notched 3 whistle(s) at 620, 1180, 2240 Hz`.

**What software cannot do:** remove broadband hash that sits under the signals at the same frequencies.
That noise has to be stopped before it reaches the radio. In order of what usually helps most:

1. **Test first.** Unplug the charger and run on battery: if decodes come back, the charger is the source.
   Plug it in again and see if the noise comes in through the **USB cable** (audio noise even with the
   antenna disconnected) or through the **antenna** (noise goes away when you disconnect the antenna).
2. **Clip-on ferrites (mix 31 for HF)** on the charger's DC lead right at the laptop, and on the USB cable at
   both ends (3-5 turns through a large core is far better than one pass).
3. **A different charger.** Cheap or third-party laptop chargers are often the worst; the maker's own, or a
   USB-C PD charger with a good name, is usually much quieter.
4. **Break the ground loop** between laptop and radio: a USB isolator (galvanic, full-speed 12 Mbit/s is
   enough for the IC-9100's codec and CAT), or run the laptop on battery while operating.
5. **Plug the charger into a different outlet** from the radio's power supply, and keep its cable away from
   the coax and the radio.
6. **Antenna away from the house** and a common-mode choke (current balun) on the coax at the feedpoint and
   where it enters the house.

Windows "USB device not recognized" when the charger is plugged in means the ground shift is upsetting the
USB link itself; a USB isolator or ferrites on the USB cable fix that too. If the slot report shows
`audio -74 dBFS ... no audio from the radio`, the codec stopped sending audio: unplug and re-plug the
radio's USB cable (or restart Uranus) after fixing the cause.
