"""Device detection, mode switching, and ADB interaction."""

import os
import json
import fcntl
import ctypes
import subprocess
import logging
from enum import Enum
from typing import Optional

import usb.core

from . import diag

logger = logging.getLogger("kdiag.device")

SG_IO = 0x2285
SG_DXFER_FROM_DEV = -3


class DeviceMode(Enum):
    DISCONNECTED = "disconnected"
    ADB = "adb"
    ADB_UNAUTHORIZED = "adb_unauthorized"
    CDROM = "cdrom"
    DIAG = "diag"


class SgIoHdr(ctypes.Structure):
    _fields_ = [
        ("interface_id", ctypes.c_int),
        ("dxfer_direction", ctypes.c_int),
        ("cmd_len", ctypes.c_ubyte),
        ("mx_sb_len", ctypes.c_ubyte),
        ("iovec_count", ctypes.c_ushort),
        ("dxfer_len", ctypes.c_uint),
        ("dxferp", ctypes.c_void_p),
        ("cmdp", ctypes.c_void_p),
        ("sbp", ctypes.c_void_p),
        ("timeout", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("pack_id", ctypes.c_int),
        ("usr_ptr", ctypes.c_void_p),
        ("status", ctypes.c_ubyte),
        ("masked_status", ctypes.c_ubyte),
        ("msg_status", ctypes.c_ubyte),
        ("sb_len_wr", ctypes.c_ubyte),
        ("host_status", ctypes.c_ushort),
        ("driver_status", ctypes.c_ushort),
        ("resid", ctypes.c_int),
        ("duration", ctypes.c_uint),
        ("info", ctypes.c_uint),
    ]


def detect_mode() -> DeviceMode:
    """Detect current device mode via USB VID:PID and ADB."""
    # Check for diag mode
    if usb.core.find(idVendor=diag.KYOCERA_VID, idProduct=diag.PID_DIAG):
        return DeviceMode.DIAG
    # Check for CDROM mode
    if usb.core.find(idVendor=diag.KYOCERA_VID, idProduct=diag.PID_CDROM):
        return DeviceMode.CDROM
    # Check for charge/ADB mode via VID:PID - still need ADB auth check
    if usb.core.find(idVendor=diag.KYOCERA_VID, idProduct=diag.PID_CHARGE):
        adb_status = _adb_auth_status()
        if adb_status == "unauthorized":
            return DeviceMode.ADB_UNAUTHORIZED
        return DeviceMode.ADB
    # Fallback: check adb devices list
    adb_status = _adb_auth_status()
    if adb_status == "device":
        return DeviceMode.ADB
    if adb_status == "unauthorized":
        return DeviceMode.ADB_UNAUTHORIZED
    return DeviceMode.DISCONNECTED


def _adb_auth_status() -> Optional[str]:
    """Check adb devices output. Returns 'device', 'unauthorized', or None."""
    try:
        r = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 2:
                # parts[1] is the status: "device", "unauthorized", "offline", etc.
                return parts[1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_device_model_adb() -> str:
    """Get device model via ADB."""
    try:
        r = subprocess.run(
            ["adb", "shell", "getprop", "ro.product.model"],
            capture_output=True, text=True, timeout=5
        )
        model = r.stdout.strip()
        return model if model else "device"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "device"


def get_device_model_diag() -> str:
    """Get device model via diag shell."""
    try:
        model = diag.exec_command("getprop ro.product.model 2>&1").strip()
        return model if model else "device"
    except Exception:
        return "device"


def adb_shell(cmd: str) -> str:
    """Execute a command via ADB shell, returns stdout+stderr."""
    try:
        r = subprocess.run(
            ["adb", "shell", cmd],
            capture_output=True, text=True, timeout=30
        )
        return r.stdout + r.stderr
    except FileNotFoundError:
        return "Error: adb not found in PATH"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"


def switch_to_adb() -> tuple:
    """Switch device back to regular ADB/charge mode via adb shell. Returns (success, message)."""
    import time

    try:
        subprocess.Popen(
            ["adb", "shell", "svc", "usb", "setFunctions"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False, "adb not found in PATH"

    # Wait for ADB mode to appear
    time.sleep(2)
    for _ in range(20):
        time.sleep(0.5)
        if detect_mode() == DeviceMode.ADB:
            return True, "Switched to ADB mode"

    return False, "Timed out waiting for ADB mode"


def switch_to_cdrom() -> bool:
    """Switch device from ADB mode to CDROM mode."""
    try:
        r = subprocess.run(
            ["adb", "shell", "svc", "usb", "setFunctions", "cdrom"],
            capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _get_cdrom_device(vendor: str = "KYOCERA", model: str = "E4810-MSS") -> Optional[str]:
    """Find the SCSI generic device for the Kyocera CDROM."""
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,TYPE,VENDOR,MODEL,SERIAL"],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None

    for device in data.get("blockdevices", []):
        if device.get("type") == "rom":
            dev_vendor = (device.get("vendor") or "").strip()
            if dev_vendor == vendor and device.get("model") == model:
                return "/dev/" + device.get("name")
    return None


def send_diag_scsi(dev_path: str, mode: int = 0x02, timeout: int = 5000) -> bool:
    """Send SCSI vendor command to switch CDROM to diag mode."""
    cdb = bytearray(10)
    cdb[0] = 0xF0
    cdb[2:6] = b"KCDT"
    cdb[8] = mode

    cdb_buffer = ctypes.create_string_buffer(bytes(cdb))
    data_buffer = ctypes.create_string_buffer(48)
    sense_buffer = ctypes.create_string_buffer(32)

    sg_io = SgIoHdr()
    sg_io.interface_id = ord("S")
    sg_io.dxfer_direction = SG_DXFER_FROM_DEV
    sg_io.cmd_len = len(cdb)
    sg_io.mx_sb_len = 32
    sg_io.dxfer_len = 48
    sg_io.dxferp = ctypes.cast(data_buffer, ctypes.c_void_p).value
    sg_io.cmdp = ctypes.cast(cdb_buffer, ctypes.c_void_p).value
    sg_io.sbp = ctypes.cast(sense_buffer, ctypes.c_void_p).value
    sg_io.timeout = timeout

    fd = None
    try:
        fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
        fcntl.ioctl(fd, SG_IO, sg_io)
    except OSError as e:
        logger.error(f"SCSI ioctl failed: {e}")
        return False
    finally:
        if fd is not None:
            os.close(fd)

    return (
        sg_io.status == 0
        and sg_io.host_status == 0
        and (sg_io.driver_status & 0x07) == 0
    )


def switch_to_diag() -> tuple[bool, str]:
    """Full ADB -> CDROM -> Diag transition. Returns (success, message)."""
    mode = detect_mode()

    if mode == DeviceMode.DIAG:
        return True, "Already in diag mode"

    if mode == DeviceMode.DISCONNECTED:
        return False, "No device detected. Ensure USB debugging is enabled."

    # Step 1: ADB -> CDROM
    if mode == DeviceMode.ADB:
        if not switch_to_cdrom():
            return False, "Failed to switch to CDROM mode via ADB"
        # Wait for CDROM device to appear
        import time
        for _ in range(20):
            time.sleep(0.5)
            if detect_mode() == DeviceMode.CDROM:
                break
        else:
            return False, "Timed out waiting for CDROM mode"

    # Step 2: CDROM -> Diag
    dev_path = _get_cdrom_device()
    if not dev_path:
        return False, "CDROM device not found"

    if not send_diag_scsi(dev_path):
        return False, "SCSI diag command failed"

    # Wait for diag device
    import time
    for _ in range(20):
        time.sleep(0.5)
        if detect_mode() == DeviceMode.DIAG:
            return True, "Switched to diag mode"

    return False, "Timed out waiting for diag mode"
