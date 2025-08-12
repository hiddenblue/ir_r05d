
# IR R05D 
NEC-like Infrared Protocol libsigrokdecode Decoder

[![License: GPL v2+](https://img.shields.io/badge/License-GPL%20v2%2B-blue.svg)](https://www.gnu.org/licenses/gpl-2.0.html)

This is a [libsigrokdecode](https://sigrok.org/wiki/Libsigrokdecode) decoder for the **R05D infrared remote control protocol**, commonly used in certain air conditioner and HVAC systems. The protocol is similar to the standard NEC infrared format but includes specific timing and data structure variations.

This decoder is designed to be used with [PulseView](https://sigrok.org/wiki/PulseView), [sigrok-cli](https://sigrok.org/wiki/Sigrok-cli), or other tools in the sigrok ecosystem for analyzing logic analyzer captures (e.g., from Saleae, Logic, or similar devices).

---

## 📌 Features

- ✅ Decodes R05D pulse-distance infrared protocol
- ✅ Detects leader codes, data bits, and separator pulses
- ✅ Parses and annotates:
  - Bytes (in **hexadecimal format**, e.g., `0xB2`)
  - Address fields
  - Command bytes (fan speed, mode, temperature)
  - Temperature values (where applicable)
  - Special separator and idle timeouts
- ✅ Supports both **active-low** and **active-high** signal polarity
- ✅ Detailed debug logging (configurable)
- ✅ Tolerance-based timing matching for robust decoding

---

## 🛠️ Usage

### Prerequisites

- [sigrok-cli](https://sigrok.org/wiki/Sigrok-cli) or [PulseView](https://sigrok.org/wiki/PulseView)
- A logic analyzer (e.g., Saleae, DreamSourceLab, etc.)
- Captured IR signal on a digital channel

### Installation

1. Clone this repository into your local sigrok decoders directory:

```bash
git clone https://github.com/your-username/ir_r05d.git
```

2. Copy the decoder to your sigrok Python decoders path:

```bash
# Typically:
cp -r ir_r05d ~/.local/share/sigrokdecode/decoders/
```

> 💡 On some systems, the path may be: `/usr/share/sigrokdecode/decoders/` or inside your Python site-packages.

3. Restart PulseView or reload decoders in sigrok-cli.

### In PulseView

1. Load your logic capture (e.g., `.sr` file).
2. Select the IR channel.
3. Go to **Decode** → **Add** → Find `IR R05D` in the list.
4. Configure options:
   - **Polarity**: Choose `active-low` (default) or `active-high`
5. Apply and view annotations for:
   - Bits
   - Bytes (`0x..`)
   - Address, Command, Temperature
   - Warnings (e.g., idle timeout)

### In sigrok-cli

```bash
sigrok-cli --input-file capture.sr \
           --protocol-decoder ir_r05d \
           --pd-option ir_r05d:polarity=active-low \
           --output-format proto
```


## Example

![20250812181709 | 900](https://markdown-1259307480.cos.ap-guangzhou.myqcloud.com/img/20250812181709.png)

![20250812181747 | 900](https://markdown-1259307480.cos.ap-guangzhou.myqcloud.com/img/20250812181747.png)

---

## 📊 Protocol Overview

| Field        | Duration (ms) | Description                     |
| ------------ | ------------- | ------------------------------- |
| Leader Low   | ~4.5 ms       | Start of transmission           |
| Leader High  | ~4.35 ms      | Follows leader low              |
| Bit Low      | ~0.6 ms       | Common low period for data bits |
| Bit 0 High   | ~0.5 ms       | Short pulse = 0                 |
| Bit 1 High   | ~1.6 ms       | Long pulse = 1                  |
| Separator    | ~5.11 ms high | Appears between data blocks     |
| Idle Timeout | ~30 ms        | End of packet detection         |

Data is transmitted MSB-first, 8 bits per byte. Typical packet structure includes:
- Device address
- Command byte(s)
- Fan speed, mode, temperature
- Checksum or repeated data

---

## 🐞 Debugging

To enable verbose debug output, edit the decoder source:

```python
DEBUG_VERBOSE = True  # Set to False to disable
LOG_FILE = None       # Optional: '/tmp/ir_r05d.log'
```

Debug logs will show:
- Edge detection
- State transitions
- Timing comparisons
- Parsing steps

---

## 📄 License

This project is licensed under the **GNU General Public License v2 or later (GPL-2.0+)**.

```
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

See <http://www.gnu.org/licenses/> for full license text.
```

---

## 🌟 Contributions

Contributions are welcome! Feel free to open issues or pull requests for:
- Timing improvements
- New command mappings
- Support for additional devices
- UI/UX enhancements in annotations

---

