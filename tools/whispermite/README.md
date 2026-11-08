# WhisperMite + Raspberry Pi

A Raspberry Pi companion for the **Kanga WhisperMite (KWM)** WSPR / QRSS beacon.

The WhisperMite already runs on its own. The Pi adds two things it can't do alone:

1. **Configure it from a script** (callsign, locator, bands, interval, QRSS) instead of typing into CoolTerm.
2. **Press the Sync button at the exact second**, using the Pi's internet (NTP) clock, on a schedule — so the beacon never drifts out of WSPR timing.

## Files

| File | Purpose |
|---|---|
| `whispermite.py` | The tool (all commands) |
| `whispermite.ini` | Your settings — edit callsign / locator / frequencies |
| `whispermite-sync.service` / `.timer` | Optional weekly automatic re-sync |

## 1. Install on the Pi

```bash
sudo apt install python3-serial python3-gpiozero
sudo usermod -aG dialout,gpio $USER      # then log out and back in
mkdir -p ~/whispermite && cd ~/whispermite   # copy the files here
```

Plug the WhisperMite into the Pi with a **data** USB cable (charge-only cables won't show a port). The CH340 chip works on Linux with no driver install.

## 2. (Optional) Wire the Sync button to the Pi

Without this, the script just tells you when to press the button. With it, the Pi presses it itself.

Use an optocoupler (e.g. PC817) so the Pi never drives the WhisperMite directly:

```
Pi GPIO17 (pin 11) ──[330 Ω]──► PC817 pin 1 (anode)
Pi GND    (pin 9)  ──────────── PC817 pin 2 (cathode)
PC817 pin 4 (collector) ─────── Sync button leg that is NOT ground
PC817 pin 3 (emitter)   ─────── Sync button leg that IS ground
```

Find the ground leg with a multimeter (continuity to the USB shell / GND). If the press does nothing, the two button wires are swapped.

## 3. Use it

```bash
python3 whispermite.py freqs                 # WSPR frequencies for F1/F2
python3 whispermite.py detect                # finds port + correct baud rate
python3 whispermite.py configure --dry-run   # preview the menu commands
python3 whispermite.py configure             # write settings to the WhisperMite
python3 whispermite.py show                  # print current settings
python3 whispermite.py send "I 20"           # any single menu command
python3 whispermite.py sync                  # press Sync on the next 10-min mark
python3 whispermite.py monitor --log kwm.log # watch serial output
```

Add `--manual` to any command to ignore GPIO and press the button yourself.

### Notes

- **Opening the serial port reboots the WhisperMite** (normal for CH340 boards). `configure`, `show`, `send`, `detect` and `monitor` all do this; `sync` never touches serial. After any of them, run `sync` again.
- The script waits for the device's *"Press Button to enter setup"* message before pressing — it deliberately does **not** press during the 5-second mode-select window, so your WSPR/QRSS mode stays as it was.
- Make sure the WhisperMite is in **WSPR mode** (left TX Tones LED only at power-up) when syncing, and that the internal **Option 1 lock switch is OFF**, or the press is ignored.
- A successful sync is confirmed by the two TX Tones LEDs blinking about 5 times. Watch for that the first time before trusting the automation.
- If spots on wsprnet.org show a consistent DT offset, trim it with `offset_ms` in the ini.
- `random_shift` uses the `R` toggle. The script reads the `?` listing to decide whether to send it; if it can't tell, it leaves it alone and says so.

## 4. Automatic weekly re-sync

```bash
sudo cp whispermite-sync.service whispermite-sync.timer /etc/systemd/system/
# edit User= and paths in the .service if you're not user 'pi'
sudo systemctl daemon-reload
sudo systemctl enable --now whispermite-sync.timer
systemctl list-timers | grep whispermite
```

The script refuses to sync if the Pi's clock isn't NTP-synchronised, so a Pi without internet won't push a wrong time into the beacon.

## Licence reminder

The WhisperMite is a transmitter: you need an amateur licence and must use your own callsign and frequencies permitted in your country (60 m especially varies).
