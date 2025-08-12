## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2025 Chase Xia<freewayrong@foxmail.com>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##

import sigrokdecode as srd
import sys
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

# Import from local module
from .lists import mode_map, fan_speed_map, temp_from_byte

# =================== Debug Configuration ===================
DEBUG_VERBOSE = False  # ✅ Set to True to enable verbose debug logging
LOG_FILE = None  # Optional: redirect output to file, e.g., '/tmp/ir_r05d.log'


def debug_print(line: int, msg: str) -> None:
    """
    Safely print debug message. Won't crash even if file write fails.
    """
    if DEBUG_VERBOSE:
        try:
            output = f"[L{line:03d}] {msg}"
            if LOG_FILE:
                try:
                    with open(LOG_FILE, 'a', encoding='utf-8') as f:
                        f.write(output + '\n')
                except Exception:
                    # Fallback to stderr if file write fails
                    print(output)
            else:
                print(output)
        except Exception:
            pass  # Final fallback: never raise an exception
    else:
        pass


# Simplified logging functions
def log_edge(level: int, samplenum: int, width: int = 0) -> None:
    """
    Log edge detection with optional pulse width.
    """
    if DEBUG_VERBOSE:
        pol = "HIGH" if level else "LOW "
        width_str = f" ({width} samples)" if width else ""
        debug_print(999, f"Edge @ {samplenum:8d} | IR={level} ({pol}){width_str}")


def log_state_transition(old: str, new: str) -> None:
    """
    Log state machine transition.
    """
    if DEBUG_VERBOSE:
        debug_print(999, f"State: {old:12s} → {new}")


# =================== Timing Constants (in ms) ===================
_TIME_TOL = 15        # Tolerance in percent
_TIME_IDLE = 30.0     # Idle timeout
_TIME_LEAD_LOW = 4.5  # Leader code low duration
_TIME_LEAD_HIGH = 4.35  # Leader code high duration
_TIME_SEP_LOW = 0.60  # Separator low duration
_TIME_SEP_HIGH = 5.11  # Separator high duration
_TIME_BIT_LOW = 0.6   # Data bit low duration
_TIME_BIT0_HIGH = 0.50  # Bit 0 high duration
_TIME_BIT1_HIGH = 1.60  # Bit 1 high duration


class STATE(Enum):
    IDLE = "IDLE"
    LEADER_LOW = "LEADER_LOW"
    LEADER_HIGH = "LEADER_HIGH"
    DATA_LOW = "DATA_LOW"
    DATA_HIGH = "DATA_HIGH"
    DATA_BIT = "DATA_BIT"
    SEP = "SEP"


class SamplerateError(Exception):
    """
    Custom exception for missing or invalid samplerate.
    """
    pass


class Ann:
    """
    Annotation types for output.
    """
    BIT, LEADER, SEPARATOR, BYTE, ADDRESS, COMMAND, PACKET, WARNING, TEMPERATURE = range(9)


class Decoder(srd.Decoder):
    """
    sigrok decoder for NEC-like R05D infrared remote control protocol.
    """
    api_version = 3
    id = 'ir_r05d'
    name = 'IR R05D'
    longname = 'NEC-like R05D Infrared'
    desc = 'R05D pulse-distance infrared remote control protocol.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['ir_r05d']
    tags = ['IR', 'Remote control', 'AC']
    channels = (
        {'id': 'ir', 'name': 'IR', 'desc': 'IR data line'},
    )
    options = (
        {'id': 'polarity', 'desc': 'Polarity', 'default': 'active-low',
         'values': ('active-low', 'active-high')},
    )
    annotations = (
        ('bit', 'Bit'),
        ('leader', 'Leader code'),
        ('separator', 'Separator'),
        ('byte', 'Byte'),
        ('address', 'Address'),
        ('command', 'Command'),
        ('packet', 'Packet'),
        ('warning', 'Warning'),
        ('temperature', 'Temperature')
    )
    annotation_rows = (
        ('bits', 'Bits', (Ann.BIT,)),
        ('codes', 'Codes', (Ann.LEADER, Ann.SEPARATOR, Ann.TEMPERATURE)),
        ('bytes', 'Bytes', (Ann.BYTE,)),
        ('fields', 'Fields', (Ann.ADDRESS, Ann.COMMAND)),
        ('packets', 'Packets', (Ann.PACKET,)),
        ('warnings', 'Warnings', (Ann.WARNING,)),
    )

    def __init__(self) -> None:
        """
        Initialize the decoder with default state and timing parameters.
        """
        self.state: STATE = STATE.IDLE
        self.bit_count: int = 0
        self.bits: List[int] = []
        self.bytes: List[int] = []
        self.byte_start: int = 0
        self.packet_start: Optional[int] = None
        self.first_block_complete: bool = False
        self.active_low: bool = True
        self.last_edge: int = 0
        self.last_pin_status: int = 1
        self.ir: int = 0
        self.out_ann: Optional[int] = None
        self.samplerate: Optional[int] = None
        self.tolerance: float = 0.0
        self.idle: int = 0
        self.lead_low: int = 0
        self.lead_high: int = 0
        self.sep_low: int = 0
        self.sep_high: int = 0
        self.bit_low: int = 0
        self.bit0_high: int = 0
        self.bit1_high: int = 0

        self.reset()
        debug_print(70, "Decoder instance created")
        debug_print(71, f"Debug mode: {'ENABLED' if DEBUG_VERBOSE else 'DISABLED'}")

    def reset(self) -> None:
        """
        Reset decoder state to IDLE and clear accumulated data.
        """
        old_state = self.state
        self.state = STATE.IDLE
        self.bit_count = 0
        self.bits = []
        self.bytes = []
        self.packet_start = None
        self.first_block_complete = False
        self.active_low = True
        self.last_edge = self.samplenum if hasattr(self, 'samplenum') else 0
        log_state_transition(old_state.value, STATE.IDLE.value)
        debug_print(73, f"Decoder reset from {old_state}")

    def start(self) -> None:
        """
        Register annotation output channel at start.
        """
        self.out_ann = self.register(srd.OUTPUT_ANN)
        debug_print(85, "Decoder started, annotations registered")

    def log_bit(self, bit: int, start: int, end: int, high_width: int) -> None:
        """
        Log detected bit with timing details (verbose only).
        """
        if DEBUG_VERBOSE:
            debug_print(999,
                        f"BIT DETECTED: {bit} | Low: {start}-{start + self.bit_low}, High: {start + self.bit_low}-{end} ({high_width} samples)")

    def metadata(self, key: int, value: Any) -> None:
        """
        Handle metadata events (e.g., samplerate).
        """
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value
            self.calc_timings()
            debug_print(91, f"Samplerate set to {value:,} Hz ({value / 1e6:.2f} MHz)")
            debug_print(92, f"Tip: 1ms = {int(self.samplerate / 1000):,} samples")

    def calc_timings(self) -> None:
        """
        Convert millisecond timing constants to sample counts based on current samplerate.
        """
        debug_print(94, "Calculating timing thresholds")
        self.tolerance = _TIME_TOL / 100.0

        def ms_to_samples(ms: float) -> int:
            return int(self.samplerate * ms / 1000.0)

        self.idle = ms_to_samples(_TIME_IDLE) - 1
        self.lead_low = ms_to_samples(_TIME_LEAD_LOW) - 1
        self.lead_high = ms_to_samples(_TIME_LEAD_HIGH) - 1
        self.sep_low = ms_to_samples(_TIME_SEP_LOW) - 1
        self.sep_high = ms_to_samples(_TIME_SEP_HIGH) - 1
        self.bit_low = ms_to_samples(_TIME_BIT_LOW) - 1
        self.bit0_high = ms_to_samples(_TIME_BIT0_HIGH) - 1
        self.bit1_high = ms_to_samples(_TIME_BIT1_HIGH) - 1

        debug_print(108, f"Timings (samples):")
        debug_print(109, f"  idle        = {self.idle:,}")
        debug_print(110, f"  lead_low    = {self.lead_low:,}")
        debug_print(111, f"  lead_high   = {self.lead_high:,}")
        debug_print(112, f"  bit_low     = {self.bit_low:,}")
        debug_print(113, f"  bit0_high   = {self.bit0_high:,}")
        debug_print(114, f"  bit1_high   = {self.bit1_high:,}")
        debug_print(115, f"  sep_low     = {self.sep_low:,}")
        debug_print(116, f"  sep_high    = {self.sep_high:,}")

    def putx(self, ss: int, es: int, ann: int, msg: List[str]) -> None:
        """
        Put annotation for general code (leader, separator, etc).
        """
        self.put(ss, es, self.out_ann, [ann, msg])

    def putb(self, ss: int, es: int, ann: int, msg: List[str]) -> None:
        """
        Put annotation specifically for bit-level events.
        """
        self.put(ss, es, self.out_ann, [ann, msg])

    def putbyte(self, ss: int, es: int, msg: List[str]) -> None:
        """
        Put annotation for a complete byte.
        """
        self.put(ss, es, self.out_ann, [Ann.BYTE, msg])

    def compare_with_tolerance(self, measured: int, base: int) -> bool:
        """
        Check if measured pulse width is within tolerance of expected base value.
        Returns True if within ±tolerance.
        """
        lower = base * (1 - self.tolerance)
        upper = base * (1 + self.tolerance)
        within = (measured >= lower) and (measured <= upper)
        if DEBUG_VERBOSE:
            expected_range = f"{int(lower):,} ~ {int(upper):,}"
            debug_print(125, f"Timing check: {measured:,} vs {expected_range} → {within}")
        return within

    def decode(self) -> None:
        """
        Main decoding loop. Processes edges and implements state machine for R05D protocol.
        """
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')

        self.active_low = (self.options['polarity'] == 'active-low')
        self.last_edge = self.samplenum
        debug_print(185, f"Polarity: {'active-low' if self.active_low else 'active-high'}")
        debug_print(186, f"Initial state: {self.state}")

        while True:
            self.last_pin_status = self.ir
            self.last_edge = self.samplenum
            (self.ir,) = self.wait({0: 'e'})  # Wait for any edge
            pulse_width: int = self.samplenum - self.last_edge

            # Log every edge
            log_edge(self.ir, self.samplenum, pulse_width)

            # --- Idle Timeout ---
            if pulse_width > self.idle:
                debug_print(300, f"pulse_width: {pulse_width} is larger than self.idle: {self.idle}")
                if self.state != STATE.IDLE:
                    debug_print(195, f"⚠️ IDLE TIMEOUT: {pulse_width:,} > {self.idle:,}")
                    self.putx(self.last_edge - pulse_width, self.last_edge, Ann.WARNING, ['Idle timeout'])
                    self.reset()
                continue

            # State machine
            debug_print(310, f"last pin status: {self.last_pin_status}, current: {self.ir}")

            if self.state == STATE.IDLE:
                if self.compare_with_tolerance(pulse_width, self.lead_low):
                    self.state = STATE.LEADER_LOW
                    log_state_transition(STATE.IDLE.value, STATE.LEADER_LOW.value)
                else:
                    debug_print(314, "cannot enter state LEADER_LOW")
                    continue

            if self.state == STATE.LEADER_LOW:
                if self.last_pin_status == 0 and self.ir == 1:
                    width = self.samplenum - self.last_edge
                    debug_print(318, f"Leader low end: {width:,} samples")
                    if self.compare_with_tolerance(width, self.lead_low):
                        self.putx(self.last_edge, self.samplenum, Ann.LEADER, ['Leader low', "LDL", "LL"])
                        self.state = STATE.LEADER_HIGH
                        log_state_transition(STATE.LEADER_LOW.value, STATE.LEADER_HIGH.value)
                    else:
                        debug_print(218, f"❌ Invalid leader low: {width:,}")
                        self.putx(self.last_edge, self.samplenum, Ann.WARNING, ['Invalid leader low'])
                        self.reset()
                else:
                    debug_print(326, "unknown status")
                    self.reset()
                continue

            elif self.state == STATE.LEADER_HIGH:
                if self.last_pin_status == 1 and self.ir == 0:
                    width = self.samplenum - self.last_edge
                    debug_print(318, f"Leader high end: {width:,} samples")
                    if self.compare_with_tolerance(width, self.lead_high):
                        self.putx(self.last_edge, self.samplenum, Ann.LEADER, ['Leader high', "LDH", 'LH'])
                        self.state = STATE.DATA_LOW
                        log_state_transition(STATE.LEADER_HIGH.value, STATE.DATA_LOW.value)
                    else:
                        debug_print(218, f"❌ Invalid leader high: {width:,}")
                        self.putx(self.last_edge, self.samplenum, Ann.WARNING, ['Invalid leader high'])
                        self.reset()
                        continue
                else:
                    debug_print(326, "unknown status")
                    self.reset()
                    continue

            if self.state == STATE.DATA_LOW:
                # Record start of packet and byte
                if self.packet_start is None:
                    self.packet_start = self.samplenum
                self.byte_start = self.samplenum

                while True:
                    self.last_pin_status = self.ir
                    self.last_edge = self.samplenum
                    (self.ir,) = self.wait({0: 'e'})
                    pulse_width = self.samplenum - self.last_edge
                    debug_print(376, f"self.bit_count: {self.bit_count}")

                    # Process full byte (8 bits)
                    if self.bit_count == 8:
                        debug_print(377, f"bits in array: {str([bit for bit in self.bits])}")
                        byte = 0
                        for bit in self.bits:
                            byte <<= 1
                            byte |= bit

                        # ✅ Only change: display byte in hex format
                        self.putbyte(self.byte_start, self.last_edge, [f"0x{byte:02X}"])

                        # Handle address byte
                        if len(self.bytes) == 0:
                            debug_print(330, f"device address {byte}")
                            self.putx(self.byte_start, self.last_edge, Ann.ADDRESS, ["Address: 0xB2", "ADDR"])

                        # Handle fan speed byte (byte index 2)
                        if len(self.bytes) == 2:
                            fan_speed_code: int = (byte & 0b11100000) >> 5
                            debug_print(336, f"fan speed code: {fan_speed_code}")
                            one_num: int = bin(fan_speed_code).count("1")
                            debug_print(336, f"one_num: {one_num}")
                            # Calculate high time for annotation
                            high_time = one_num * self.bit1_high + (6 - one_num) * self.bit_low
                            self.putx(self.byte_start, self.byte_start + high_time,
                                      Ann.COMMAND, [str(fan_speed_map.get(fan_speed_code, "Unknown"))])

                        # Handle temperature and mode byte (byte index 4)
                        if len(self.bytes) == 4:
                            temp_code: int = (byte & 0b11110000) >> 4
                            debug_print(332, f"temp_code {temp_code}")
                            temperature: int = temp_from_byte(temp_code)
                            one_num = bin(temperature).count("1")
                            if temperature != 31:
                                high_time = one_num * self.bit1_high + (8 - one_num) * self.bit_low
                                self.putx(self.byte_start, self.byte_start + high_time,
                                          Ann.TEMPERATURE, [f"{temperature}°C"])
                                debug_print(333, f"current temperature {temperature}")
                            else:
                                debug_print(337, f"error decoding temperature byte {byte}")

                            mode_code: int = (byte & 0b00001100) >> 2
                            debug_print(341, f"mode code {mode_code}")
                            mid_point: int = self.byte_start + (one_num * self.bit1_high + (8 - one_num) * self.bit_low)
                            debug_print(356, f"mid_point: {mid_point}")
                            one_num_mode = bin(mode_code).count("1")
                            debug_print(359, f"mode code one_num: {one_num_mode}")

                            if temp_code == 0b1110:
                                debug_print(352, "no valid temperature code, in fan mode")
                                high_time = one_num_mode * self.bit1_high + (2 - one_num_mode) * self.bit_low
                                self.putx(mid_point, mid_point + high_time, Ann.COMMAND, ["Fan"])
                            else:
                                high_time = one_num_mode * self.bit1_high + (2 - one_num_mode) * self.bit_low
                                self.putx(mid_point, mid_point + high_time,
                                          Ann.COMMAND, [str(mode_map.get(mode_code, "Unknown"))])

                        self.byte_start = self.last_edge
                        self.bytes.append(byte)
                        self.bits = []
                        self.bit_count = 0

                    # Log edge again inside loop
                    log_edge(self.ir, self.samplenum, pulse_width)

                    # Transition from DATA_LOW
                    if self.state == STATE.DATA_LOW:
                        if self.compare_with_tolerance(pulse_width, self.bit_low):
                            debug_print(398, f"self.bytes size: {len(self.bytes)} self.bits: {self.bits}")
                            # After 6 bytes, next low may be separator
                            if len(self.bytes) == 6 and len(self.bits) == 0:
                                self.state = STATE.SEP
                            else:
                                self.state = STATE.DATA_HIGH
                            log_state_transition(STATE.DATA_LOW.value, self.state.value)
                        else:
                            debug_print(372, "unknown status")
                    elif self.state == STATE.DATA_HIGH:
                        if self.compare_with_tolerance(pulse_width, self.bit0_high):
                            self.putb(self.last_edge - self.bit_low, self.samplenum, self.out_ann, ["0"])
                            self.bits.append(0)
                            self.bit_count += 1
                            self.state = STATE.DATA_LOW
                            log_state_transition(STATE.DATA_HIGH.value, STATE.DATA_LOW.value)
                        elif self.compare_with_tolerance(pulse_width, self.bit1_high):
                            self.putb(self.last_edge - self.bit_low, self.samplenum, self.out_ann, ["1"])
                            self.bits.append(1)
                            self.bit_count += 1
                            self.state = STATE.DATA_LOW
                            log_state_transition(STATE.DATA_HIGH.value, STATE.DATA_LOW.value)
                        else:
                            debug_print(385, "bit recognition error!")
                            self.reset()
                    elif self.state == STATE.SEP and self.bit_count == 0:
                        # Check for long high pulse indicating separator
                        if pulse_width > self.sep_high * (1 - self.tolerance):
                            end_es = min(self.samplenum, self.last_edge + self.sep_high)
                            self.putx(self.last_edge - self.bit_low, end_es, Ann.SEPARATOR, ["Separator", "SEP", "S"])
                            debug_print(422, "encounter a sep unit")
                            self.state = STATE.LEADER_LOW
                            self.bytes = []
                            self.bit_count = 0
                            break
                    continue