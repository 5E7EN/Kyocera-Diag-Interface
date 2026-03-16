"""HDLC framing for Qualcomm Diag transport."""

import struct
from typing import Optional

HDLC_FLAG = 0x7E
HDLC_ESCAPE = 0x7D
HDLC_XOR = 0x20


def crc16(data: bytes) -> int:
    """CRC-16/CCITT (poly 0x8408, init 0xFFFF, inverted)."""
    crc = 0xFFFF
    for b in data:
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (b ^ crc) & 1 else crc >> 1
            b >>= 1
    return (~crc) & 0xFFFF


def encode(payload: bytes) -> bytes:
    """Append CRC, escape reserved bytes, wrap in 0x7E delimiter."""
    data = payload + struct.pack("<H", crc16(payload))
    frame = bytearray()
    for b in data:
        if b in (HDLC_FLAG, HDLC_ESCAPE):
            frame.extend([HDLC_ESCAPE, b ^ HDLC_XOR])
        else:
            frame.append(b)
    frame.append(HDLC_FLAG)
    return bytes(frame)


def decode(frame: bytes) -> Optional[bytes]:
    """Strip delimiter, unescape, verify CRC, return payload."""
    raw = frame[:-1] if frame.endswith(bytes([HDLC_FLAG])) else frame
    data = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == HDLC_ESCAPE and i + 1 < len(raw):
            data.append(raw[i + 1] ^ HDLC_XOR)
            i += 2
        else:
            data.append(raw[i])
            i += 1
    if len(data) < 3:
        return None
    payload, rx_crc = data[:-2], struct.unpack("<H", data[-2:])[0]
    if crc16(payload) != rx_crc:
        return None
    return bytes(payload)
