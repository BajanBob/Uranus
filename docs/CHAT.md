# Chat over Pumpkin and Cucumber

Keyboard-to-keyboard text at signal levels where voice is impossible.

## How it works

* **Frames:** every transmission carries one frame, either an **ID frame**
  (your callsign and grid) or a **text frame** of 11 characters.
* **Where text frames live:** in code space a callsign never uses, so
  beacon decoders cannot mistake them for stations. Each frame has its own
  CRC check.
* **Longer messages:** these are split into 11-character frames, each with a
  sequence number and a "more follows" flag. The receiver joins them back
  together and marks any missing part with `[...]`.
* **Taking turns:** as in FT8, one station sends in even slots and the
  other in odd slots.
* **Identification:** your callsign goes out before your first message and
  again at least every 10 minutes. Text is plain and never encrypted.
* **Characters sent:** letters, digits, space and `+ - . / ?`. Other
  punctuation is converted.

## Speed and sensitivity

| Mode | Radio | Speed | Works down to |
|---|---|---|---|
| PUMPKIN-15 | SSB, GPS-locked | about 44 characters a minute | −24.7 dB (2500 Hz) |
| PUMPKIN-60 | SSB, GPS-locked | about 11 characters a minute | −30.8 dB (2500 Hz) |
| CUCUMBER-15 | any FM radio | about 44 characters a minute | about −11 dB in a 12.5 kHz channel |
| CUCUMBER-60 | any FM radio | about 11 characters a minute | about −13 dB in a 12.5 kHz channel |

**Bandwidth:** Pumpkin occupies under 40 Hz, and Cucumber one ordinary
12.5 kHz FM channel. Both are well inside amateur bandwidth limits. Check
your national rules.

## Use it

* **In the Uranus window:** press **Chat**, choose the mode, frequency and
  slots (hover over any control for help), then press **Start**. **Demo**
  sends your message through a simulated weak channel, with no radio needed.
* **From the command line:**

```bash
python -m uranus chat --submode CUCUMBER-15 --freq 223.420 --slot even
python -m uranus chat-demo "CQ 220 DE 8P5AB" --submode CUCUMBER-15 --level -8
```
