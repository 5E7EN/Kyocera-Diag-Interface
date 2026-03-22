#!/usr/bin/env python3
"""
Reboot a Kyocera device into fastboot mode via kdiag.
Requires: pyusb, libusb backend, adb in PATH, and sudo/admin privileges.

Install dependencies:
    pip install pyusb

Open an admin terminal and run with:
    python3 fastboot_standalone.py

To return to normal boot afterwards:
    fastboot erase chkcode
    fastboot reboot
"""

import os
import sys
import json
import struct
import time
import subprocess

import usb.core
import usb.util

# -- Kyocera USB IDs --
VID = 0x0482
PID_ADB = 0x0A9B
PID_CDROM = 0x0A8F
PID_DIAG = 0x0A9D

# -- Diag protocol constants --
DIAG_SUBSYS_CMD_F = 0x4B
KDIAG_SUBSYS_ID = 0xFC
CMD_SHELL = 0x2081
CMD_REBOOT = 0x2012
CMD_BLOCKDEV = 0x2000

# BlockDevIO sub-commands and flags
SUBCMD_OPEN = 0x0000
SUBCMD_WRITE = 0x0003
SUBCMD_CLOSE = 0x0001
O_WRONLY = 0x0001
O_CREAT = 0x0040
O_TRUNC = 0x0200

# The magic that tells the bootloader to enter fastboot
CHKCODE_PARTITION = "/dev/block/bootdevice/by-name/chkcode"
CHKCODE_MAGIC = b"LOOTBFCK" + b"\xff" * 8

# HDLC framing bytes
HDLC_FLAG = 0x7E
HDLC_ESC = 0x7D
HDLC_XOR = 0x20

BANNER = r"""
BS"D
 _  __                             ___         _   _                _
| |/ /  _  _  ___  __ ___  _ _ __ | __| __ _ _| |_| |__  ___  ___ | |_
| ' <  | || |/ _ \/ _/ -_)| '_/ _|| _| / _` (_-<  _| '_ \/ _ \/ _ \|  _|
|_|\_\  \_, |\___/\__\___||_| \__||_|  \__,_/__/\__|_.__/\___/\___/ \__|
        |__/

  Credits: @5E7EN/BenTorah, @LeoBuskin
  https://github.com/5E7EN/Kyocera-Diag-Interface
"""


# ============================================================
# HDLC framing (diag transport layer)
# ============================================================

def _crc16(data):
    """CRC-16/CCITT used by the diag protocol."""
    crc = 0xFFFF
    for b in data:
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (b ^ crc) & 1 else crc >> 1
            b >>= 1
    return (~crc) & 0xFFFF


def hdlc_encode(payload):
    """Wrap payload with CRC and HDLC escape framing."""
    data = payload + struct.pack("<H", _crc16(payload))
    frame = bytearray()
    for b in data:
        if b in (HDLC_FLAG, HDLC_ESC):
            frame.extend([HDLC_ESC, b ^ HDLC_XOR])
        else:
            frame.append(b)
    frame.append(HDLC_FLAG)
    return bytes(frame)


def hdlc_decode(frame):
    """Strip HDLC framing and verify CRC. Returns payload or None."""
    raw = frame[:-1] if frame.endswith(bytes([HDLC_FLAG])) else frame
    data = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == HDLC_ESC and i + 1 < len(raw):
            data.append(raw[i + 1] ^ HDLC_XOR)
            i += 2
        else:
            data.append(raw[i])
            i += 1
    if len(data) < 3:
        return None
    payload, rx_crc = data[:-2], struct.unpack("<H", data[-2:])[0]
    return bytes(payload) if _crc16(payload) == rx_crc else None


# ============================================================
# Low-level diag USB communication
# ============================================================

def _diag_header(cmd):
    """Build the 4-byte diag subsystem header."""
    return bytes([DIAG_SUBSYS_CMD_F, KDIAG_SUBSYS_ID, cmd & 0xFF, (cmd >> 8) & 0xFF])


def _blockdev_header(subcmd):
    """Build the 6-byte BlockDevIO header."""
    return struct.pack(
        "<BBBBH",
        DIAG_SUBSYS_CMD_F, KDIAG_SUBSYS_ID,
        CMD_BLOCKDEV & 0xFF, (CMD_BLOCKDEV >> 8) & 0xFF,
        subcmd,
    )


def _transact(ep_out, ep_in, pkt, match_len=4, timeout=5.0):
    """Send an HDLC packet and wait for a matching response."""
    header = pkt[:match_len]
    ep_out.write(hdlc_encode(pkt))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = ep_in.read(16384, timeout=500)
        except usb.core.USBTimeoutError:
            continue
        payload = hdlc_decode(bytes(raw))
        if payload and payload[:match_len] == header:
            return payload
    return None


def _find_diag_device():
    """Find the Kyocera diag USB device and return (dev, iface, ep_out, ep_in)."""
    dev = usb.core.find(idVendor=VID, idProduct=PID_DIAG)
    if not dev:
        return None, None, None, None

    cfg = dev.get_active_configuration()
    for intf in cfg:
        # Diag interface is vendor-class but not ADB (subclass 0x42)
        if intf.bInterfaceClass != 0xFF or intf.bInterfaceSubClass == 0x42:
            continue
        ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
        )
        if ep_out and ep_in:
            # Detach kernel driver if needed (Linux only)
            try:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    dev.detach_kernel_driver(intf.bInterfaceNumber)
            except (usb.core.USBError, NotImplementedError):
                pass
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
            return dev, intf.bInterfaceNumber, ep_out, ep_in

    return None, None, None, None


# ============================================================
# Diag shell & reboot commands
# ============================================================

def diag_exec(ep_out, ep_in, cmd):
    """Run a shell command via the diag protocol."""
    pkt = _diag_header(CMD_SHELL) + cmd.encode() + b"\x00"
    header = pkt[:4]
    ep_out.write(hdlc_encode(pkt))

    chunks = []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            raw = ep_in.read(16384, timeout=500)
        except usb.core.USBTimeoutError:
            if chunks:
                break
            continue
        payload = hdlc_decode(bytes(raw))
        if not payload or not payload.startswith(header):
            continue
        if len(payload) < 9:
            break
        chunk = payload[9:].rstrip(b"\x00").decode("ascii", errors="replace")
        if chunk:
            chunks.append(chunk)
        if payload[8]:  # final flag
            break
    return "".join(chunks)


def diag_reboot(ep_out):
    """Send the reboot command. Device drops off USB immediately."""
    try:
        ep_out.write(hdlc_encode(_diag_header(CMD_REBOOT)))
    except usb.core.USBError:
        pass  # expected - device is already rebooting


# ============================================================
# BlockDevIO: write chkcode magic to partition
# ============================================================

def blockdev_write(ep_out, ep_in, path, data):
    """Open a partition, write data, close. Returns True on success."""
    # Open for writing (truncate if exists, create if not)
    flags = O_WRONLY | O_CREAT | O_TRUNC
    pkt = _blockdev_header(SUBCMD_OPEN) + struct.pack("<IHH", flags, 0o644, 0) + path.encode() + b"\x00"
    resp = _transact(ep_out, ep_in, pkt, match_len=6)
    if not resp or len(resp) < 16:
        return False
    status = struct.unpack_from("<H", resp, 6)[0]
    fd = struct.unpack_from("<I", resp, 8)[0]
    if status != 0 or fd > 4:
        return False

    # Write in chunks (protocol max is 1024 bytes per write)
    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + 1024]
        pkt = _blockdev_header(SUBCMD_WRITE) + struct.pack("<II", fd, len(chunk)) + chunk
        resp = _transact(ep_out, ep_in, pkt, match_len=6)
        if not resp or len(resp) < 16:
            _blockdev_close(ep_out, ep_in, fd)
            return False
        if struct.unpack_from("<H", resp, 6)[0] != 0:
            _blockdev_close(ep_out, ep_in, fd)
            return False
        written = struct.unpack_from("<i", resp, 8)[0]
        if written < 0:
            _blockdev_close(ep_out, ep_in, fd)
            return False
        offset += written

    return _blockdev_close(ep_out, ep_in, fd)


def _blockdev_close(ep_out, ep_in, fd):
    """Close a BlockDevIO file descriptor."""
    pkt = _blockdev_header(SUBCMD_CLOSE) + struct.pack("<I", fd)
    resp = _transact(ep_out, ep_in, pkt, match_len=6)
    if not resp or len(resp) < 12:
        return False
    return struct.unpack_from("<H", resp, 6)[0] == 0


# ============================================================
# Mode switching: ADB -> CDROM -> Diag
# ============================================================

def wait_for_usb(pid, timeout=15):
    """Poll until a device with the given PID appears on USB."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if usb.core.find(idVendor=VID, idProduct=pid):
            return True
        time.sleep(0.5)
    return False


def switch_adb_to_cdrom():
    """Tell the device to present itself as a CDROM."""
    print("    Switching ADB -> CDROM...")
    r = subprocess.run(
        ["adb", "shell", "svc", "usb", "setFunctions", "cdrom"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ADB command failed: {r.stderr.strip()}")
    if not wait_for_usb(PID_CDROM):
        raise RuntimeError("Timed out waiting for CDROM mode")


def find_cdrom_device():
    """Locate the Kyocera CDROM block device path (platform-specific)."""
    if sys.platform == "linux":
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,TYPE,VENDOR,MODEL"],
            capture_output=True, text=True, timeout=10,
        )
        for dev in json.loads(r.stdout).get("blockdevices", []):
            if dev.get("type") == "rom" and "KYOCERA" in (dev.get("vendor") or "").upper():
                return "/dev/" + dev["name"]

    elif sys.platform == "darwin":
        # macOS: scan external disks for Kyocera vendor string
        for i in range(6):
            path = f"/dev/disk{i}"
            if os.path.exists(path):
                info = subprocess.run(
                    ["diskutil", "info", path], capture_output=True, text=True, timeout=5
                )
                if "KYOCERA" in info.stdout.upper():
                    return path

    else:
        # Windows: try PowerShell WMI query first, then probe CdRom paths
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_CDROMDrive | Select-Object -Property Id,Name | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=10,
            )
            data = json.loads(r.stdout)
            if isinstance(data, dict):
                data = [data]
            for drive in data:
                name = (drive.get("Name") or "").upper()
                drive_id = drive.get("Id") or ""
                if "KYOCERA" in name or "E4810" in name or "E4610" in name:
                    if not drive_id.startswith("\\\\"):
                        drive_id = f"\\\\.\\{drive_id}"
                    return drive_id
        except Exception:
            pass

        # Fallback: probe \\.\CdRom0 through \\.\CdRom9
        import ctypes, ctypes.wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.wintypes.HANDLE
        k32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        INVALID = ctypes.wintypes.HANDLE(-1).value
        for i in range(10):
            path = f"\\\\.\\CdRom{i}"
            h = k32.CreateFileW(path, 0x80000000, 0x01, None, 3, 0, None)
            if h != INVALID:
                k32.CloseHandle(h)
                return path

    return None


def send_scsi_diag_switch(dev_path):
    """Send the Kyocera SCSI vendor command to switch CDROM -> Diag mode."""
    # CDB: vendor-specific opcode 0xF0 with "KCDT" magic, mode byte 0x02 = diag
    cdb = bytearray(10)
    cdb[0] = 0xF0
    cdb[2:6] = b"KCDT"
    cdb[8] = 0x02

    if sys.platform == "linux":
        import ctypes, fcntl

        class SgIoHdr(ctypes.Structure):
            _fields_ = [
                ("interface_id", ctypes.c_int), ("dxfer_direction", ctypes.c_int),
                ("cmd_len", ctypes.c_ubyte), ("mx_sb_len", ctypes.c_ubyte),
                ("iovec_count", ctypes.c_ushort), ("dxfer_len", ctypes.c_uint),
                ("dxferp", ctypes.c_void_p), ("cmdp", ctypes.c_void_p),
                ("sbp", ctypes.c_void_p), ("timeout", ctypes.c_uint),
                ("flags", ctypes.c_uint), ("pack_id", ctypes.c_int),
                ("usr_ptr", ctypes.c_void_p), ("status", ctypes.c_ubyte),
                ("masked_status", ctypes.c_ubyte), ("msg_status", ctypes.c_ubyte),
                ("sb_len_wr", ctypes.c_ubyte), ("host_status", ctypes.c_ushort),
                ("driver_status", ctypes.c_ushort), ("resid", ctypes.c_int),
                ("duration", ctypes.c_uint), ("info", ctypes.c_uint),
            ]

        cdb_buf = ctypes.create_string_buffer(bytes(cdb))
        data_buf = ctypes.create_string_buffer(48)
        sense_buf = ctypes.create_string_buffer(32)

        sg = SgIoHdr()
        sg.interface_id = ord("S")
        sg.dxfer_direction = -3  # SG_DXFER_FROM_DEV
        sg.cmd_len = len(cdb)
        sg.mx_sb_len = 32
        sg.dxfer_len = 48
        sg.dxferp = ctypes.cast(data_buf, ctypes.c_void_p).value
        sg.cmdp = ctypes.cast(cdb_buf, ctypes.c_void_p).value
        sg.sbp = ctypes.cast(sense_buf, ctypes.c_void_p).value
        sg.timeout = 5000

        fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, 0x2285, sg)  # SG_IO ioctl
        finally:
            os.close(fd)

        if sg.status != 0 or sg.host_status != 0:
            raise RuntimeError(f"SCSI command failed (status={sg.status})")

    elif sys.platform == "win32":
        import ctypes, ctypes.wintypes
        k32 = ctypes.windll.kernel32

        # Set proper 64-bit types or handles get truncated on x64
        k32.CreateFileW.restype = ctypes.wintypes.HANDLE
        k32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        k32.DeviceIoControl.argtypes = [
            ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
            ctypes.c_void_p, ctypes.wintypes.DWORD,
            ctypes.c_void_p, ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.DWORD), ctypes.c_void_p,
        ]
        k32.DeviceIoControl.restype = ctypes.wintypes.BOOL

        INVALID = ctypes.wintypes.HANDLE(-1).value
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_RW = 0x03
        OPEN_EXISTING = 3

        class SPT(ctypes.Structure):
            _fields_ = [
                ("Length", ctypes.c_ushort), ("ScsiStatus", ctypes.c_ubyte),
                ("PathId", ctypes.c_ubyte), ("TargetId", ctypes.c_ubyte),
                ("Lun", ctypes.c_ubyte), ("CdbLength", ctypes.c_ubyte),
                ("SenseInfoLength", ctypes.c_ubyte), ("DataIn", ctypes.c_ubyte),
                ("DataTransferLength", ctypes.c_ulong), ("TimeOutValue", ctypes.c_ulong),
                ("DataBufferOffset", ctypes.c_size_t), ("SenseInfoOffset", ctypes.c_ulong),
                ("Cdb", ctypes.c_ubyte * 16),
            ]

        class SPTWB(ctypes.Structure):
            _fields_ = [("spt", SPT), ("sense", ctypes.c_ubyte * 32), ("data", ctypes.c_ubyte * 48)]

        sptwb = SPTWB()
        ctypes.memset(ctypes.byref(sptwb), 0, ctypes.sizeof(sptwb))
        sptwb.spt.Length = ctypes.sizeof(SPT)
        sptwb.spt.CdbLength = len(cdb)
        sptwb.spt.SenseInfoLength = 32
        sptwb.spt.DataIn = 1  # SCSI_IOCTL_DATA_IN
        sptwb.spt.DataTransferLength = 48
        sptwb.spt.TimeOutValue = 5
        sptwb.spt.DataBufferOffset = SPTWB.data.offset
        sptwb.spt.SenseInfoOffset = SPTWB.sense.offset
        for i, b in enumerate(cdb):
            sptwb.spt.Cdb[i] = b

        h = k32.CreateFileW(
            dev_path, GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_RW, None, OPEN_EXISTING, 0, None,
        )
        if h == INVALID:
            raise RuntimeError(f"Cannot open {dev_path} (error {ctypes.GetLastError()})")

        ret = ctypes.wintypes.DWORD(0)
        # Lock + dismount so Windows releases its grip on the volume
        k32.DeviceIoControl(h, 0x00090018, None, 0, None, 0, ctypes.byref(ret), None)
        k32.DeviceIoControl(h, 0x00090020, None, 0, None, 0, ctypes.byref(ret), None)

        sz = ctypes.sizeof(sptwb)
        ok = k32.DeviceIoControl(h, 0x4D004, ctypes.byref(sptwb), sz, ctypes.byref(sptwb), sz, ctypes.byref(ret), None)
        err = ctypes.GetLastError()

        # Unlock + close
        k32.DeviceIoControl(h, 0x0009001C, None, 0, None, 0, ctypes.byref(ret), None)
        k32.CloseHandle(h)

        if not ok:
            raise RuntimeError(f"SCSI DeviceIoControl failed (win32 error {err})")
        if sptwb.spt.ScsiStatus != 0:
            raise RuntimeError(f"SCSI command failed (ScsiStatus={sptwb.spt.ScsiStatus})")

    else:
        raise RuntimeError(f"SCSI passthrough not implemented for {sys.platform}")


def switch_to_diag():
    """Full ADB -> CDROM -> Diag mode transition."""
    # Already in diag?
    if usb.core.find(idVendor=VID, idProduct=PID_DIAG):
        print("    Already in diag mode.")
        return

    # Need ADB to start the chain
    if not usb.core.find(idVendor=VID, idProduct=PID_ADB):
        # Could already be in CDROM mode from a previous attempt
        if not usb.core.find(idVendor=VID, idProduct=PID_CDROM):
            raise RuntimeError("No Kyocera device found on USB")
    else:
        switch_adb_to_cdrom()
        time.sleep(1)

    # CDROM -> Diag via SCSI vendor command
    print("    Switching CDROM -> Diag...")
    cdrom_path = find_cdrom_device()
    if not cdrom_path:
        raise RuntimeError("Could not locate CDROM device path")

    send_scsi_diag_switch(cdrom_path)

    if not wait_for_usb(PID_DIAG):
        raise RuntimeError("Timed out waiting for diag mode")


def _print_zadig_hint():
    """Print Zadig driver install instructions when USB access fails on Windows."""
    if sys.platform != "win32":
        return
    print()
    print("  ** Windows requires libusb and the correct USB driver for diag mode. **")
    print()
    print("  libusb setup:")
    print("    1. Download libusb: https://github.com/libusb/libusb/releases")
    print("    2. Extract VS2022/MS64/dll/libusb-1.0.dll from the archive")
    print("    3. Place it next to your python.exe")
    print("       (likely %LOCALAPPDATA%\\Programs\\Python\\Python3xx)")
    print()
    print("  Zadig driver setup (one-time, required for diag mode):")
    print("    1. Download and run Zadig: https://zadig.akeo.ie/")
    print("    2. Find 'KYOCERA_Android (Interface 0)' in the dropdown")
    print("       - USB ID should be: 0482 0A9D 00")
    print("    3. Select WinUSB as the driver and click 'Install Driver'")
    print("    4. Disconnect and reconnect the device, then re-run this script")
    print()
    print("  Note: Windows Insider builds may require disabling driver signature enforcement.")
    print()


# ============================================================
# Main
# ============================================================

def main():
    print(BANNER)

    try:
        # Step 1 - get into diag mode (ADB -> CDROM -> Diag)
        print("[1/5] Switching to diag mode...")
        switch_to_diag()
        print("      OK\n")

        # Step 2 - open the diag USB interface
        print("[2/5] Connecting to diag interface...")
        try:
            dev, iface, ep_out, ep_in = _find_diag_device()
        except usb.core.USBError as e:
            print(f"      FAIL: USB error: {e}")
            _print_zadig_hint()
            return 1
        if not dev:
            print("      FAIL: Could not open diag USB interface.")
            _print_zadig_hint()
            return 1
        print("      OK\n")

        # Step 3 - activate diag daemons (BlockDevIO needs them)
        print("[3/5] Starting diag daemons...")
        try:
            diag_exec(ep_out, ep_in, "setprop vendor.kc.diag.status start")
        except usb.core.USBError as e:
            print(f"      FAIL: USB error during diag command: {e}")
            _print_zadig_hint()
            return 1
        time.sleep(2)
        print("      OK\n")

        # Step 4 - write the chkcode magic bytes
        print("[4/5] Writing fastboot flag...")
        try:
            ok = blockdev_write(ep_out, ep_in, CHKCODE_PARTITION, CHKCODE_MAGIC)
        except usb.core.USBError as e:
            print(f"      FAIL: USB error during partition write: {e}")
            _print_zadig_hint()
            return 1
        if not ok:
            print("      FAIL: Write failed.")
            return 1
        print("      OK\n")

        # Step 5 - reboot the device
        print("[5/5] Rebooting device...")
        diag_reboot(ep_out)

        # Clean up USB resources
        try:
            usb.util.release_interface(dev, iface)
            usb.util.dispose_resources(dev)
        except Exception:
            pass

        print("      Device is rebooting into fastboot mode.\n")
        print("  To return to normal boot afterwards, run:")
        print("    $ fastboot erase chkcode")
        print("    $ fastboot reboot\n")
        return 0

    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
