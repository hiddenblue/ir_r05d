##  
## This file is part of the libsigrokdecode project.  
##  
## Copyright (C) 2025 Anonymous  
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

# 已知设备地址（前6字节中的AA'部分）
address = {
    0xB2: 'Generic R05D AC (Default)',  # A = 0xB2 固定
}

# 命令解码表：根据BB'CC'字段解释功能
# 示例：B=0xBF (10111111), C=0x18 (00011000) → 自动模式、自动风速、26℃
command = {
    0xB2: {  # 对应地址 AA' = 0xB2
        # (BB', CC') -> [描述, 简写]
        # 使用元组作为键
        (0xBF, 0x18): ['Auto 26°C', 'Auto26'],
        (0xBF, 0x08): ['Auto 25°C', 'Auto25'],
        (0xBF, 0x28): ['Auto 27°C', 'Auto27'],
        (0xEF, 0x18): ['Cool 26°C', 'Cool26'],
        (0xCF, 0x18): ['Dry  26°C', 'Dry26'],
        (0xAF, 0x18): ['Fan  Auto', 'FanA'],
        (0x6F, 0x18): ['Heat 26°C', 'Heat26'],
        # 更多可扩展...
    }
}

# 风速、模式、温度等字段解析辅助表（可选）
mode_map = {
    0b10: 'Auto',
    0b00: 'Cool',
    0b01: 'Dry',
    0b11: 'Heat',
}
#     0b01: 'Fan',

fan_speed_map = {
    0b101: 'Auto',
    0b001: 'High',
    0b010: 'Med',
    0b100: 'Low',
    0b000: "Const",
    0b011: "Poweroff"
}


# 温度提取函数（从CC字节中解析）
def temp_from_byte(codec: int) -> int:
    # r05d温度是用数值转换成格雷码，然后+17度表示的

    # if codec == 0b1110:
    #     print("error temperature codec")
    #     return None
    temp_map = {
        0b0000: 0,
        0b0001: 1,
        0b0011: 2,
        0b0010: 3,
        0b0110: 4,
        0b0111: 5,
        0b0101: 6,
        0b0100: 7,
        0b1100: 8,
        0b1101: 9,
        0b1001: 10,
        0b1000: 11,
        0b1010: 12,
        0b1011: 13,
        0b1110: 14}
    return temp_map[codec] + 17
