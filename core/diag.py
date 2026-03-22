"""Kyocera Diag USB protocol: packet building, USB I/O, and high-level commands."""

import base64
import struct
import time
import logging
from typing import Optional, Tuple

import usb.core
import usb.util

from . import hdlc

logger = logging.getLogger("kdiag.diag")

# USB identifiers
KYOCERA_VID = 0x0482
PID_DIAG = 0x0A9D  # Diag mode
PID_CDROM = 0x0A8F  # CDROM mode
PID_CHARGE = 0x0A9B  # Regular "Charge only" mode

# Diag protocol constants
DIAG_SUBSYS_CMD_F = 0x4B
KDIAG_SUBSYS_ID = 0xFC

# Command codes
CMD_READ_BUILD_ID = 0x2040
CMD_READ_PRODUCT = 0x2041
CMD_SHELL_OUTPUT = 0x2081
CMD_READ_RESET_STATUS = 0x2061
CMD_READ_FACTORY_MODE = 0x20C1
CMD_WRITE_FACTORY_MODE = 0x20C0
CMD_REBOOT = 0x2012

# Factory mode flags
FACTORY_PERMISSIVE = 0x04
FACTORY_CLEAR = 0x00


def _header(cmd_code: int) -> bytes:
    """4-byte subsystem header."""
    return bytes(
        [
            DIAG_SUBSYS_CMD_F,
            KDIAG_SUBSYS_ID,
            cmd_code & 0xFF,
            (cmd_code >> 8) & 0xFF,
        ]
    )


def _transact(ep_out, ep_in, pkt: bytes, timeout: float = 2.0) -> Optional[bytes]:
    """Send HDLC-framed packet, return first matching response."""
    header = pkt[:4]
    ep_out.write(hdlc.encode(pkt))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = ep_in.read(16384, timeout=500)
        except usb.core.USBTimeoutError:
            continue
        payload = hdlc.decode(bytes(raw))
        if payload and payload[:4] == header:
            return payload
    return None


def find_device(vid: int = KYOCERA_VID, pid: int = PID_DIAG):
    """Find USB device by VID:PID, return (dev, iface, ep_out, ep_in) or Nones."""
    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if not dev:
        return None, -1, None, None
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError as e:
        logger.error(f"Cannot open USB device: {e}")
        return None, -1, None, None
    for intf in cfg:
        if intf.bInterfaceClass != 0xFF or intf.bInterfaceSubClass == 0x42:
            continue
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_IN,
        )
        if ep_out and ep_in:
            try:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    dev.detach_kernel_driver(intf.bInterfaceNumber)
            except (usb.core.USBError, NotImplementedError):
                # is_kernel_driver_active / detach not supported on Windows
                pass
            return dev, intf.bInterfaceNumber, ep_out, ep_in
    return None, -1, None, None


# --- Read commands ---


def read_build_id(ep_out, ep_in) -> dict:
    payload = _transact(ep_out, ep_in, _header(CMD_READ_BUILD_ID))
    if not payload or len(payload) < 7:
        return {"ok": False, "raw": payload.hex() if payload else ""}
    overflow = struct.unpack_from("<H", payload, 4)[0]
    str_len = payload[6]
    value = payload[7 : 7 + str_len].rstrip(b"\x00").decode("ascii", errors="replace")
    return {"ok": True, "value": value, "truncated": overflow > 0}


def read_product_model(ep_out, ep_in) -> dict:
    payload = _transact(ep_out, ep_in, _header(CMD_READ_PRODUCT))
    if not payload or len(payload) < 6:
        return {"ok": False, "raw": payload.hex() if payload else ""}
    overflow = struct.unpack_from("<H", payload, 4)[0]
    value = payload[6:].rstrip(b"\x00").decode("ascii", errors="replace")
    return {"ok": True, "value": value, "truncated": overflow > 0}


def read_reset_status(ep_out, ep_in) -> dict:
    payload = _transact(ep_out, ep_in, _header(CMD_READ_RESET_STATUS))
    if not payload or len(payload) < 10:
        return {"ok": False, "raw": payload.hex() if payload else ""}
    dnand_status = struct.unpack_from("<h", payload, 4)[0]
    reset_data = struct.unpack_from("<I", payload, 6)[0]
    return {
        "ok": dnand_status == 0,
        "dnand_status": dnand_status,
        "reset_data": reset_data,
    }


def read_factory_cmdline(ep_out, ep_in) -> dict:
    payload = _transact(ep_out, ep_in, _header(CMD_READ_FACTORY_MODE))
    if not payload or len(payload) < 10:
        return {"ok": False, "raw": payload.hex() if payload else ""}
    dnand_status = struct.unpack_from("<H", payload, 4)[0]
    flags = struct.unpack_from("<I", payload, 6)[0]
    return {
        "ok": dnand_status == 0,
        "dnand_status": dnand_status,
        "flags": flags,
        "kcfactory": bool(flags & 0x1),
        "kcmount": bool(flags & 0x2),
        "kcpermissive": bool(flags & 0x4),
    }


# --- Shell execution ---


# --- Persistent connection ---

_conn = None  # Cached (dev, iface, ep_out, ep_in)


def _get_connection(vid: int = KYOCERA_VID, pid: int = PID_DIAG):
    """Get or create a persistent USB connection to the diag device."""
    global _conn
    # Always close previous connection to avoid stale endpoints after re-enumeration
    if _conn is not None:
        _close_stale()

    dev, iface, ep_out, ep_in = find_device(vid, pid)
    if not dev:
        return None, -1, None, None
    try:
        usb.util.claim_interface(dev, iface)
    except usb.core.USBError as e:
        logger.error(f"Failed to claim interface: {e}")
        try:
            dev.reset()
            usb.util.claim_interface(dev, iface)
        except Exception:
            return None, -1, None, None
    _conn = (dev, iface, ep_out, ep_in)
    return dev, iface, ep_out, ep_in


def _close_stale():
    """Best-effort cleanup of a stale connection."""
    global _conn
    if _conn is None:
        return
    dev, iface, _, _ = _conn
    _conn = None
    try:
        usb.util.release_interface(dev, iface)
    except Exception:
        pass
    try:
        usb.util.dispose_resources(dev)
    except Exception:
        pass


def close_connection():
    """Release the persistent USB connection."""
    _close_stale()


def reboot() -> bool:
    """Reboot the device."""
    dev, _, ep_out, _ = _get_connection()
    if not dev:
        raise ConnectionError("Diag device not found")
    try:
        # Fire and forget - device reboots before it can respond
        ep_out.write(hdlc.encode(_header(CMD_REBOOT)))
        return True
    except Exception:
        return True  # USB error after write likely means device already rebooting
    finally:
        usb.util.dispose_resources(dev)


def exec_command(
    cmd: str, vid: int = KYOCERA_VID, pid: int = PID_DIAG, timeout_s: float = 10.0
) -> str:
    """Execute shell command via diag and return stdout."""
    dev, _, ep_out, ep_in = _get_connection(vid, pid)
    if not dev:
        raise ConnectionError("Diag device not found")
    cmd_bytes = cmd.encode()
    if len(cmd_bytes) > 1023:
        raise ValueError(f"Command too long ({len(cmd_bytes)} bytes, max 1023)")
    pkt = _header(CMD_SHELL_OUTPUT) + cmd_bytes + b"\x00"
    header = pkt[:4]
    ep_out.write(hdlc.encode(pkt))

    chunks = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            raw = ep_in.read(16384, timeout=500)
        except usb.core.USBTimeoutError:
            if chunks:
                break
            continue
        payload = hdlc.decode(bytes(raw))
        if not payload or not payload.startswith(header):
            continue
        if len(payload) < 9:
            break
        final_flag = payload[8]
        chunk = payload[9:].rstrip(b"\x00").decode("ascii", errors="replace")
        if chunk:
            chunks.append(chunk)
        if final_flag:
            break
    return "".join(chunks)


# --- Probe ---


def probe(vid: int = KYOCERA_VID, pid: int = PID_DIAG) -> dict:
    """Read-only probe. Returns dict with all results."""
    dev, _, ep_out, ep_in = _get_connection(vid, pid)
    if not dev:
        raise ConnectionError("Diag device not found")
    results = {
        "build_id": read_build_id(ep_out, ep_in),
        "product": read_product_model(ep_out, ep_in),
        "reset_status": read_reset_status(ep_out, ep_in),
        "factory_cmdline": read_factory_cmdline(ep_out, ep_in),
    }
    results["all_ok"] = all(r["ok"] for r in results.values())
    return results


# --- SELinux ---


def set_factory_flag(flags: int, vid: int = KYOCERA_VID, pid: int = PID_DIAG) -> bool:
    """Write factory mode flag to DNAND ID 9."""
    dev, iface, ep_out, ep_in = _get_connection(vid, pid)
    if not dev:
        raise ConnectionError("Diag device not found")
    pkt = _header(CMD_WRITE_FACTORY_MODE) + struct.pack("<BBBB", flags, 0, 0, 0)
    payload = _transact(ep_out, ep_in, pkt, timeout=2.0)
    if payload and len(payload) >= 6:
        status = struct.unpack_from("<H", payload, 4)[0]
        return status == 0
    return False


# --- File pull ---


def pull_file(
    remote_path: str,
    local_path: str,
    chunk_size: int = 4096,
    vid: int = KYOCERA_VID,
    pid: int = PID_DIAG,
    progress_cb=None,
) -> bool:
    """Pull a file via diag shell using chunked base64. progress_cb(offset, total) called per chunk."""
    dev, iface, ep_out, ep_in = _get_connection(vid, pid)
    if not dev:
        raise ConnectionError("Diag device not found")

    # Get file size
    size_out = _exec_shell(ep_out, ep_in, f"wc -c < {remote_path} 2>/dev/null")
    cleaned = "".join(c for c in size_out if c.isdigit() or c in (" ", "\n"))
    try:
        file_size = int(cleaned.strip().split()[0])
    except (ValueError, IndexError):
        raise RuntimeError(f"Cannot determine file size: {size_out!r}")

    with open(local_path, "wb") as f:
        offset = 0
        while offset < file_size:
            to_read = min(chunk_size, file_size - offset)
            cmd = f"dd if={remote_path} bs=1 skip={offset} count={to_read} 2>/dev/null | base64 -w 0"
            b64 = _exec_shell(ep_out, ep_in, cmd, timeout_s=15.0).strip()
            if not b64:
                raise RuntimeError(f"Empty response at offset {offset}")
            chunk = base64.b64decode(b64)
            f.write(chunk)
            offset += len(chunk)
            if progress_cb:
                progress_cb(offset, file_size)
            if len(chunk) < to_read:
                break
    return True


def _exec_shell(ep_out, ep_in, cmd: str, timeout_s: float = 10.0) -> str:
    """Raw shell exec on already-claimed interface."""
    pkt = _header(CMD_SHELL_OUTPUT) + cmd.encode() + b"\x00"
    header = pkt[:4]
    ep_out.write(hdlc.encode(pkt))

    chunks = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            raw = ep_in.read(16384, timeout=500)
        except usb.core.USBTimeoutError:
            if chunks:
                break
            continue
        payload = hdlc.decode(bytes(raw))
        if not payload or not payload.startswith(header):
            continue
        if len(payload) < 9:
            break
        final_flag = payload[8]
        chunk = payload[9:].rstrip(b"\x00").decode("ascii", errors="replace")
        if chunk:
            chunks.append(chunk)
        if final_flag:
            break
    return "".join(chunks)
