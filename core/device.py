"""Device detection, mode switching, and ADB interaction."""

import os
import sys
import json
import ctypes
import subprocess
import logging
import time
from enum import Enum
from typing import Optional

import usb.core

from . import diag

logger = logging.getLogger("kdiag.device")


class DeviceMode(Enum):
    DISCONNECTED = "disconnected"
    ADB = "adb"
    ADB_UNAUTHORIZED = "adb_unauthorized"
    CDROM = "cdrom"
    DIAG = "diag"


# ---------------------------------------------------------------------------
# Platform-specific SCSI passthrough
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes.wintypes

    # Set proper 64-bit return/arg types for kernel32 functions
    _kernel32 = ctypes.windll.kernel32
    _kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    _kernel32.DeviceIoControl.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _kernel32.DeviceIoControl.restype = ctypes.wintypes.BOOL
    _kernel32.GetDriveTypeW.restype = ctypes.c_uint

    # IOCTL_SCSI_PASS_THROUGH — non-direct variant where data buffer is inline
    IOCTL_SCSI_PASS_THROUGH = 0x4D004
    SCSI_IOCTL_DATA_IN = 1  # Device -> Host

    class ScsiPassThrough(ctypes.Structure):
        """SCSI_PASS_THROUGH structure (non-direct, uses DataBufferOffset)."""

        _fields_ = [
            ("Length", ctypes.c_ushort),
            ("ScsiStatus", ctypes.c_ubyte),
            ("PathId", ctypes.c_ubyte),
            ("TargetId", ctypes.c_ubyte),
            ("Lun", ctypes.c_ubyte),
            ("CdbLength", ctypes.c_ubyte),
            ("SenseInfoLength", ctypes.c_ubyte),
            ("DataIn", ctypes.c_ubyte),
            ("DataTransferLength", ctypes.c_ulong),
            ("TimeOutValue", ctypes.c_ulong),
            ("DataBufferOffset", ctypes.c_size_t),  # ULONG_PTR
            ("SenseInfoOffset", ctypes.c_ulong),
            ("Cdb", ctypes.c_ubyte * 16),
        ]

    class ScsiPassThroughWithBuffers(ctypes.Structure):
        """SCSI_PASS_THROUGH + inline sense and data buffers."""

        _fields_ = [
            ("spt", ScsiPassThrough),
            ("sense", ctypes.c_ubyte * 32),
            ("data", ctypes.c_ubyte * 48),
        ]

    def _get_cdrom_device(
        vendor: str = "KYOCERA", model: str = "E4810-MSS"
    ) -> Optional[str]:
        r"""Find the Kyocera CDROM using \\.\CdRomN device path on Windows.

        Uses CdRomN paths instead of drive letters to bypass the volume manager,
        which blocks SCSI passthrough when no medium is present.
        """
        try:
            # PowerShell: get CDROM device index, matching by name
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_CDROMDrive | Select-Object -Property Id,Name,MediaLoaded | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = json.loads(result.stdout)
            # Normalize to list (single result comes back as a dict)
            if isinstance(data, dict):
                data = [data]
            for drive in data:
                name = (drive.get("Name") or "").upper()
                drive_id = drive.get("Id") or ""
                if "KYOCERA" in name or "E4810" in name or "E4610" in name:
                    # Id is a drive letter like "E:" — make it a device path
                    if not drive_id.startswith("\\\\"):
                        drive_id = f"\\\\.\\{drive_id}"
                    logger.info(f"Found Kyocera CDROM: {drive_id} ({name})")
                    return drive_id
        except (
            subprocess.CalledProcessError,
            json.JSONDecodeError,
            FileNotFoundError,
        ) as e:
            logger.debug(f"PowerShell CDROM detection failed: {e}")

        # Fallback: probe \\.\CdRom0 through \\.\CdRom9
        OPEN_EXISTING = 3
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x01
        INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value
        for i in range(10):
            path = f"\\\\.\\CdRom{i}"
            handle = _kernel32.CreateFileW(
                path,
                GENERIC_READ,
                FILE_SHARE_READ,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            if handle != INVALID_HANDLE_VALUE:
                _kernel32.CloseHandle(handle)
                logger.info(f"Fallback: using first available CDROM: {path}")
                return path
        return None

    # Volume IOCTLs needed to release Windows grip on the CDROM :-)
    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_DISMOUNT_VOLUME = 0x00090020
    FSCTL_UNLOCK_VOLUME = 0x0009001C

    def send_diag_scsi(dev_path: str, mode: int = 0x02, timeout: int = 5) -> bool:
        """Send SCSI vendor command via IOCTL_SCSI_PASS_THROUGH on Windows."""
        cdb = bytearray(10)
        cdb[0] = 0xF0
        cdb[2:6] = b"KCDT"
        cdb[8] = mode

        sptwb = ScsiPassThroughWithBuffers()
        ctypes.memset(ctypes.byref(sptwb), 0, ctypes.sizeof(sptwb))
        spt = sptwb.spt
        spt.Length = ctypes.sizeof(ScsiPassThrough)
        spt.CdbLength = len(cdb)
        spt.SenseInfoLength = 32
        spt.DataIn = SCSI_IOCTL_DATA_IN
        spt.DataTransferLength = 48
        spt.TimeOutValue = timeout
        spt.DataBufferOffset = ScsiPassThroughWithBuffers.data.offset
        spt.SenseInfoOffset = ScsiPassThroughWithBuffers.sense.offset

        for i, b in enumerate(cdb):
            spt.Cdb[i] = b

        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x01
        FILE_SHARE_WRITE = 0x02
        OPEN_EXISTING = 3
        INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value

        handle = _kernel32.CreateFileW(
            dev_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            err = ctypes.GetLastError()
            logger.error(f"CreateFileW failed for {dev_path}: error {err}")
            return False

        bytes_returned = ctypes.wintypes.DWORD(0)

        # Lock and dismount the volume so Windows releases its hold on the CDROM
        _kernel32.DeviceIoControl(
            handle,
            FSCTL_LOCK_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(bytes_returned),
            None,
        )
        _kernel32.DeviceIoControl(
            handle,
            FSCTL_DISMOUNT_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(bytes_returned),
            None,
        )

        buf_size = ctypes.sizeof(sptwb)
        ok = _kernel32.DeviceIoControl(
            handle,
            IOCTL_SCSI_PASS_THROUGH,
            ctypes.byref(sptwb),
            buf_size,
            ctypes.byref(sptwb),
            buf_size,
            ctypes.byref(bytes_returned),
            None,
        )
        err = ctypes.GetLastError()

        # Unlock and close
        _kernel32.DeviceIoControl(
            handle,
            FSCTL_UNLOCK_VOLUME,
            None,
            0,
            None,
            0,
            ctypes.byref(bytes_returned),
            None,
        )
        _kernel32.CloseHandle(handle)

        if not ok:
            logger.error(f"DeviceIoControl SCSI_PASS_THROUGH failed: error {err}")
            return False

        if spt.ScsiStatus != 0:
            sense_key = sptwb.sense[2] & 0x0F if sptwb.sense[0] != 0 else 0
            asc = sptwb.sense[12] if len(sptwb.sense) > 12 else 0
            ascq = sptwb.sense[13] if len(sptwb.sense) > 13 else 0
            logger.error(
                f"SCSI command failed: ScsiStatus={spt.ScsiStatus}, "
                f"SenseKey={sense_key}, ASC/ASCQ={asc:02X}h/{ascq:02X}h"
            )
            return False

        return True

else:
    # Linux / POSIX
    import fcntl

    SG_IO = 0x2285
    SG_DXFER_FROM_DEV = -3

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

    def _get_cdrom_device(
        vendor: str = "KYOCERA", model: str = "E4810-MSS"
    ) -> Optional[str]:
        """Find the SCSI generic device for the Kyocera CDROM on Linux."""
        try:
            result = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,TYPE,VENDOR,MODEL,SERIAL"],
                capture_output=True,
                text=True,
                check=True,
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
        """Send SCSI vendor command to switch CDROM to diag mode on Linux."""
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


# ---------------------------------------------------------------------------
# Platform-independent functions
# ---------------------------------------------------------------------------


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
        r = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=5
        )
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
            capture_output=True,
            text=True,
            timeout=5,
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
            ["adb", "shell", cmd], capture_output=True, text=True, timeout=30
        )
        return r.stdout + r.stderr
    except FileNotFoundError:
        return "Error: adb not found in PATH"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"


def reboot(mode: "DeviceMode | None" = None) -> None:
    if mode == DeviceMode.DIAG:
        # Activate other diag daemons
        # Gotta do this since kc_diag class only launches if prop is set
        # (see /vendor/etc/init/init.kdmc.rc)
        diag.exec_command("setprop vendor.kc.diag.status start")
        time.sleep(3)
        # Reboot
        diag.reboot()
    else:
        # Reboot via ADB
        subprocess.run(["adb", "reboot"], timeout=10, capture_output=True)


# Fastboot reboot constants
_CHKCODE_PARTITION = "/dev/block/bootdevice/by-name/chkcode"
_CHKCODE_MAGIC = b"LOOTBFCK" + b"\xff" * 8


def reboot_to_fastboot() -> tuple:
    """Write chkcode magic and reboot."""
    printf_arg = "".join("\\%03o" % b for b in _CHKCODE_MAGIC)
    part = _CHKCODE_PARTITION

    try:
        # Zero the partition
        out = diag.exec_command(
            f"dd if=/dev/zero of={part} bs=512 count=1024 2>&1 && sync",
            timeout_s=30.0,
        )

        # Write magic
        out = diag.exec_command(
            f"printf '{printf_arg}' | dd of={part} bs=16 count=1 2>&1 && sync",
        )

        # Verify looks good
        out = diag.exec_command(
            f"dd if={part} bs=16 count=1 2>/dev/null | od -t x1 -A none",
        )
        result = out.strip().replace(" ", "")
        expected = "".join("%02x" % b for b in _CHKCODE_MAGIC)

        if result != expected:
            return False, "Verification failed. Magic did not work."

        # Reboot
        try:
            diag.exec_command("/system/bin/reboot")
        except Exception:
            # Connection drop is expected, ignore error
            pass

        return True, (
            "Device will boot into fastboot mode.\n"
            "To return to normal boot after you're finished, run:\n"
            "  fastboot erase chkcode\n"
            "  fastboot reboot"
        )
    except ConnectionError as e:
        return False, f"Diag connection failed: {e}"
    except Exception as e:
        return False, f"Fastboot reboot failed: {e}"


def switch_to_adb() -> tuple:
    """Switch device back to regular ADB/charge mode via adb shell. Returns (success, message)."""
    import time

    diag.close_connection()

    try:
        subprocess.Popen(
            ["adb", "shell", "svc", "usb", "setFunctions"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


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
