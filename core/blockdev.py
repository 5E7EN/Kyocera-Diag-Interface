# Device must have the BlockDevIO daemon running (triggered by `setprop vendor.kc.diag.status start`).
# AKA `ensure_daemons()`


import struct
import time
from typing import Optional

import usb.core

from . import hdlc
from .diag import DIAG_SUBSYS_CMD_F, KDIAG_SUBSYS_ID

# Protocol constants
CMD_BLOCK_DEV_IO = 0x2000

SUBCMD_OPEN  = 0x0000
SUBCMD_CLOSE = 0x0001
SUBCMD_READ  = 0x0002
SUBCMD_WRITE = 0x0003

O_RDONLY = 0x0000
O_WRONLY = 0x0001
O_CREAT  = 0x0040
O_TRUNC  = 0x0200

# Packet helpers

def _hdr(subcmd: int) -> bytes:
    """6-byte subsystem header for BlockDevIO commands."""
    return struct.pack(
        "<BBBBH",
        DIAG_SUBSYS_CMD_F,
        KDIAG_SUBSYS_ID,
        CMD_BLOCK_DEV_IO & 0xFF,
        (CMD_BLOCK_DEV_IO >> 8) & 0xFF,
        subcmd,
    )


def _transact(ep_out, ep_in, pkt: bytes, timeout: float = 5.0) -> Optional[bytes]:
    """Send HDLC-framed packet, return first response matching the 6-byte header."""
    header = pkt[:6]
    ep_out.write(hdlc.encode(pkt))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = ep_in.read(16384, timeout=500)
        except usb.core.USBTimeoutError:
            continue
        payload = hdlc.decode(bytes(raw))
        if payload and payload[:6] == header:
            return payload
    return None


# Open / close / write

def open_path(ep_out, ep_in, path: str, flags: int, mode: int) -> Optional[int]:
    """Open a block device path. Returns fd (0-4) or None on failure."""
    pkt = (
        _hdr(SUBCMD_OPEN)
        + struct.pack("<IHH", flags, mode, 0)
        + path.encode("ascii")
        + b"\x00"
    )
    resp = _transact(ep_out, ep_in, pkt)
    if not resp or len(resp) < 16:
        return None
    status = struct.unpack_from("<H", resp, 6)[0]
    fd     = struct.unpack_from("<I", resp, 8)[0]
    return fd if status == 0 and fd <= 4 else None


def close_path(ep_out, ep_in, fd: int) -> bool:
    """Close a previously opened fd. Returns True on success."""
    pkt = _hdr(SUBCMD_CLOSE) + struct.pack("<I", fd)
    resp = _transact(ep_out, ep_in, pkt)
    if not resp or len(resp) < 12:
        return False
    return struct.unpack_from("<H", resp, 6)[0] == 0


def write_partition(ep_out, ep_in, path: str, data: bytes) -> bool:
    """Open path for writing (truncating), write data in <=1024-byte chunks, close."""
    fd = open_path(ep_out, ep_in, path, O_WRONLY | O_CREAT | O_TRUNC, 0o644)
    if fd is None:
        return False

    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + 1024]
        pkt = _hdr(SUBCMD_WRITE) + struct.pack("<II", fd, len(chunk)) + chunk
        resp = _transact(ep_out, ep_in, pkt)
        if not resp or len(resp) < 16:
            close_path(ep_out, ep_in, fd)
            return False
        status  = struct.unpack_from("<H", resp, 6)[0]
        written = struct.unpack_from("<i", resp, 8)[0]
        if status != 0 or written < 0:
            close_path(ep_out, ep_in, fd)
            return False
        offset += written

    return close_path(ep_out, ep_in, fd)
