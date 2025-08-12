##
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

from typing import Optional, List, Dict, Any
import sigrokdecode as srd
import sys
from .lists import address, command, mode_map, fan_speed_map, temp_from_byte
from enum import Enum

# =================== 调试配置 ===================
DEBUG_VERBOSE = True  # ✅ 设为 True 开启详细调试日志
LOG_FILE = None       # 可选：重定向到文件，如 '/tmp/ir_r05d.log'

def debug_print(line: int, msg: str) -> None:
    """安全打印调试信息，即使写文件失败也不崩溃"""
    try:
        output = f"[L{line:03d}] {msg}"
        if LOG_FILE:
            try:
                with open(LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(output + '\n')
            except Exception:
                # 文件写入失败则降级到 stderr
                print(output)
        else:
            print(output)
    except Exception:
        pass  # 最终兜底，绝不抛异常

# 简化日志函数
def log_edge(level: int, samplenum: int, width: int = 0) -> None:
    if DEBUG_VERBOSE:
        pol = "HIGH" if level else "LOW "
        width_str = f" ({width} samples)" if width else ""
        debug_print(999, f"Edge @ {samplenum:8d} | IR={level} ({pol}){width_str}")

def log_state_transition(old: str, new: str) -> None:
    if DEBUG_VERBOSE:
        debug_print(999, f"State: {old:12s} → {new}")



# =================== 时间常量 ===================
_TIME_TOL        = 15      # 容差 %
_TIME_IDLE       = 30.0    # 空闲超时 ms
_TIME_LEAD_LOW   = 4.5     # 引导码低电平
_TIME_LEAD_HIGH  = 4.35    # 引导码高电平
_TIME_SEP_LOW    = 0.60    # 分隔符低电平
_TIME_SEP_HIGH   = 5.11    # 分隔符高电平
_TIME_BIT_LOW    = 0.6     # 数据位低电平
_TIME_BIT0_HIGH  = 0.50    # 数据0高电平
_TIME_BIT1_HIGH  = 1.60    # 数据1高电平

class STATE(Enum):
    IDLE = "IDLE"
    LEADER_LOW = "LEADER_LOW"
    LEADER_HIGH = "LEADER_HIGH"
    DATA_LOW = "DATA_LOW"
    DATA_HIGH = "DATA_HIGH"
    DATA_BIT = "DATA_BIT"
    SEP = "SEP"

    

class SamplerateError(Exception):
    pass

class Ann:
    BIT, LEADER, SEPARATOR, BYTE, ADDRESS, COMMAND, PACKET, WARNING, TEMPERATURE = range(9)

class Decoder(srd.Decoder):
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
        self.state = 'IDLE'
        self.bit_count = 0
        self.bits = []
        self.bytes = []
        self.byte_start = 0
        self.packet_start = None
        self.first_block_complete = False
        self.active_low = True
        self.last_edge = 0
        self.last_pin_status = 1
        self.ir = 0
        self.out_ann = None
        self.samplerate = None
        self.tolerance = 0.0
        self.idle = 0
        self.lead_low = 0
        self.lead_high = 0
        self.sep_low = 0
        self.sep_high = 0
        self.bit_low = 0
        self.bit0_high = 0
        self.bit1_high = 0

        self.reset()
        debug_print(70, "Decoder instance created")
        debug_print(71, f"Debug mode: {'ENABLED' if DEBUG_VERBOSE else 'DISABLED'}")

    def reset(self) -> None:
        old_state = self.state
        self.state = STATE.IDLE
        self.bit_count = 0
        self.bits = []
        self.bytes = []
        self.packet_start = None
        self.first_block_complete = False
        self.active_low = True
        self.last_edge = self.samplenum if hasattr(self, 'samplenum') else 0

        log_state_transition(old_state, STATE.IDLE)
        debug_print(73, f"Decoder reset from {old_state}")

    def start(self) -> None:
        self.out_ann = self.register(srd.OUTPUT_ANN)
        debug_print(85, "Decoder started, annotations registered")

    def log_bit(self, bit: int, start: int, end: int, high_width: int) -> None:
        if DEBUG_VERBOSE:
            debug_print(999, f"BIT DETECTED: {bit} | Low: {start}-{start+self.bit_low}, High: {start+self.bit_low}-{end} ({high_width} samples)")

    def metadata(self, key: int, value: Any) -> None:
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value
            self.calc_timings()
            debug_print(91, f"Samplerate set to {value:,} Hz ({value / 1e6:.2f} MHz)")
            debug_print(92, f"Tip: 1ms = {int(self.samplerate / 1000):,} samples")

    def calc_timings(self) -> None:
        debug_print(94, "Calculating timing thresholds")
        self.tolerance = _TIME_TOL / 100.0

        def ms_to_samples(ms: float) -> int:
            return int(self.samplerate * ms / 1000.0)

        self.idle = ms_to_samples(_TIME_IDLE)-1
        self.lead_low = ms_to_samples(_TIME_LEAD_LOW)-1
        self.lead_high = ms_to_samples(_TIME_LEAD_HIGH)-1
        self.sep_low = ms_to_samples(_TIME_SEP_LOW)-1
        self.sep_high = ms_to_samples(_TIME_SEP_HIGH)-1
        self.bit_low = ms_to_samples(_TIME_BIT_LOW)-1
        self.bit0_high = ms_to_samples(_TIME_BIT0_HIGH)-1
        self.bit1_high = ms_to_samples(_TIME_BIT1_HIGH)-1

        debug_print(108, f"Timings (samples):")
        debug_print(109, f"  idle        = {self.idle:,}")
        debug_print(110, f"  lead_low    = {self.lead_low:,}")
        debug_print(111, f"  lead_high   = {self.lead_high:,}")
        debug_print(112, f"  bit_low     = {self.bit_low:,}")
        debug_print(113, f"  bit0_high   = {self.bit0_high:,}")
        debug_print(114, f"  bit1_high   = {self.bit1_high:,}")
        debug_print(115, f"  sep_low     = {self.sep_low:,}")
        debug_print(116, f"  sep_high    = {self.sep_high:,}")

        # 输出引导码注释
    def putx(self, ss: int, es: int, ann: int, msg: List[str]) -> None:
        self.put(ss, es, self.out_ann, [ann, msg])

    # 输出 bit注释
    def putb(self, ss: int, es: int, ann: int, msg: List[str]) -> None:
        self.put(ss, es, self.out_ann, [ann, msg])

    def putbyte(self, ss: int, es: int, msg: List[str]) -> None:
        self.put(ss, es, self.out_ann, [Ann.BYTE, msg])

    def putpacket(self, data: List[Any]) -> None:
        if self.packet_start is not None:
            self.put(self.packet_start, self.samplenum, self.out_ann, data)

    def compare_with_tolerance(self, measured: int, base: int) -> bool:
        within = (measured >= base * (1 - self.tolerance)) and (measured <= base * (1 + self.tolerance))
        if DEBUG_VERBOSE:
            expected_range = f"{int(base*(1-self.tolerance)):,} ~ {int(base*(1+self.tolerance)):,}"
            debug_print(125, f"Timing check: {measured:,} vs {expected_range} → {within}")
        return within

    def decode(self) -> None:
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')

        self.active_low = (self.options['polarity'] == 'active-low')
        self.last_edge = self.samplenum
        debug_print(185, f"Polarity: {'active-low' if self.active_low else 'active-high'}")
        debug_print(186, f"Initial state: {self.state}")

        while True:
            self.last_pin_status = self.ir
            self.last_edge = self.samplenum
            (self.ir,) = self.wait({0: 'e'})
            pulse_width:int = self.samplenum - self.last_edge

            # 记录每个边沿
            log_edge(self.ir, self.samplenum, pulse_width)

            # --- 空闲超时 ---
            if pulse_width > self.idle:
                debug_print(300, f"pulse_width: {pulse_width} is largger than self.idle: {self.idle}")
                if self.state != STATE.IDLE:
                    debug_print(195, f"⚠️ IDLE TIMEOUT: {pulse_width:,} > {self.idle:,}")
                    debug_print(302, f"the status of ")
                    self.putx(self.last_edge - pulse_width, self.last_edge, Ann.WARNING, ['Idle timeout'])
                    self.reset()
                continue

            # 状态机

            debug_print(310, f"last pin status:{self.last_pin_status}, current: {self.ir}")

            if self.state == STATE.IDLE:
                if self.compare_with_tolerance(pulse_width, self.lead_low):
                    self.state = STATE.LEADER_LOW
                    log_state_transition(STATE.IDLE, STATE.LEADER_LOW)
                else:
                    debug_print(314, "can not enter state LEADER_LOW")
                    continue

            
            if self.state == STATE.LEADER_LOW:
                
                if self.last_pin_status == 0 and self.ir == 1:
                    width = self.samplenum - self.last_edge
                    debug_print(318, f"Leader low end: {width:,} samples")
                    if self.compare_with_tolerance(width, self.lead_low):
                        self.putx(self.last_edge, self.samplenum, Ann.LEADER, ['Leader low'])
                        self.state = STATE.LEADER_HIGH
                        log_state_transition(STATE.LEADER_LOW, STATE.LEADER_HIGH)

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
                        self.putx(self.last_edge, self.samplenum, Ann.LEADER, ['Leader high'])
                        self.state = STATE.DATA_LOW
                        log_state_transition(STATE.LEADER_HIGH, STATE.DATA_LOW)
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
                # 记录数据位的起始位置
                self.packet_start = self.samplenum
                self.byte_start = self.samplenum
                while True:
                    self.last_pin_status = self.ir
                    self.last_edge = self.samplenum
                    (self.ir,) = self.wait({0: 'e'})
                    pulse_width:int = self.samplenum - self.last_edge

                    debug_print(376,  f"self.bit_count:{self.bit_count}")

                    if self.bit_count == 8:
                        debug_print(377, f"the bits in arrry:{str([bit for bit in self.bits])}")
                        byte = 0
                        for bit in self.bits:
                            byte <<= 1
                            byte |= bit
                        # 这里处理末端和开始要注意，因为分成了两段
                        self.putbyte(self.byte_start, self.last_edge, [str(byte)])

                        if len(self.bytes) == 0:
                            debug_print(330, f"device address{byte}")
                            self.putx(self.byte_start, self.last_edge, Ann.ADDRESS, [str("Address: 0xB2")])


                        # 处理风速代码 B4 B3 B2 B1 B0

                        if len(self.bytes) == 2:
                            fan_speed_code:int = (byte & 0b11100000) >> 5
                            debug_print(336, f"fan speed code:{fan_speed_code}")
                            one_num:int = bin(fan_speed_code).count("1") 
                            debug_print(336, f"one_num: {one_num}")
                            self.putx(self.byte_start, self.byte_start + (one_num* self.bit1_high + (6-one_num)*self.bit_low), Ann.COMMAND, [str(fan_speed_map.get(fan_speed_code))])

                        # 处理温度注释 不准
                        if len(self.bytes) == 4:

                            # 抽湿有温度代码， 送风无
                            temp_code: int = (byte & 0b11110000) >> 4
                            debug_print(332, f"temp_code {temp_code}")
                            temperature: int = temp_from_byte(temp_code)
                            one_num = bin(temperature).count("1")
                            if temperature != 31 :
                                self.putx(self.byte_start, self.byte_start+(one_num * self.bit1_high + (8-one_num)*self.bit_low), Ann.TEMPERATURE, [str(temperature) +"°C" ])
                                debug_print(333, f"current temperature {temperature}")
                            else:
                                debug_print(337, f"error decode the temperature byte {byte}")

                            mode_code:int = (byte & 0b00001100) >> 2
                            debug_print(341, f"mode code {mode_code}")
                            mid_point: int = self.byte_start+(one_num * self.bit1_high + (8-one_num)*self.bit_low)
                            debug_print(356, f"mid_point: {mid_point}")
                            one_num = bin(mode_code).count("1")

                            debug_print(359, f"mode code one_num: {one_num}")

                            if temp_code == 0b1110:
                                debug_print(352, "no valid temperature code, in fan mode")
                                self.putx(mid_point, mid_point+(one_num * self.bit1_high+(2-one_num) * self.bit_low), Ann.COMMAND, ["Fan"])
                            else:
                                self.putx(mid_point, mid_point+(one_num * self.bit1_high+ (2-one_num) * self.bit_low), Ann.COMMAND, [str(mode_map.get(mode_code))])
                        
                            


                        self.byte_start = self.last_edge
                        self.bytes.append(byte)
                        self.bits = []
                        self.bit_count = 0

                    # 记录每个边沿
                    log_edge(self.ir, self.samplenum, pulse_width)

                    # 0 和 1共有的相同低电平
                    # bit当中的低点评和分隔符当中的低电平相同。
                    if self.state == STATE.DATA_LOW:
                        if self.compare_with_tolerance(pulse_width, self.bit_low):

                            debug_print(398, f"self.bytes size: {len(self.bytes)} self.bits: {self.bits}")

                            if len(self.bytes) == 6 and len(self.bits) == 0:
                                # 进入分隔符模式
                                self.state = STATE.SEP
                            else:
                                self.state = STATE.DATA_HIGH
                            log_state_transition(STATE.DATA_LOW, self.state)
                        else: 
                            debug_print(372, f"unknown status")
                    elif self.state == STATE.DATA_HIGH:
                        if self.compare_with_tolerance(pulse_width, self.bit0_high):
                            self.putb(self.last_edge - self.bit_low, self.samplenum, self.out_ann, [str(0)])
                            self.bits.append(0)
                            self.bit_count += 1
                            self.state  = STATE.DATA_LOW
                            log_state_transition(STATE.DATA_HIGH, self.state)

                        elif self.compare_with_tolerance(pulse_width, self.bit1_high):
                            self.putb(self.last_edge - self.bit_low, self.samplenum,self.out_ann, [str(1)])
                            self.bits.append(1)
                            self.bit_count += 1
                            self.state = STATE.DATA_LOW
                            log_state_transition(STATE.DATA_HIGH, self.state)
                        else:
                            debug_print(385, "bit recongnition error!")
                            self.reset()
                    elif self.state == STATE.SEP and self.bit_count == 0:
                        if  pulse_width >self.sep_high * (1 - self.tolerance):
                            self.putx(self.last_edge - self.bit_low, min(self.samplenum, self.last_edge + self.sep_high), Ann.SEPARATOR, ["separator"])
                            debug_print(422, "encounter a sep unit")
                            self.state = STATE.LEADER_LOW
                            self.bytes = []
                            self.bit_count = 0
                            break
                    continue




                    

                    
                    







