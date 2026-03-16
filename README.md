# Kyocera Diag Interface

GUI tool for interacting with Kyocera devices via ADB and Qualcomm diagnostic mode.

Tested on E4610 and E4810. Other Kyocera devices with the same Qualcomm diag interface may work but are untested.  
Also tested on an old C7642 device running Android 5.1.1 - which shares the diag protocol. Switching to diag mode is done via hidden dailer menu (##DIAG#) after MSL code auth, though.

### ⚠️ Disclaimer: I take no responsibility for anything that happens to your device as a result of using this tool.

### Writing to /system or verified partitions on a locked bootloader (via Shell tab) will brick your device!

## Features

- Switch between ADB and Qualcomm diagnostic mode seamlessly
- Execute shell commands with root access via diag mode
- View and change SELinux enforcement state
- Pull files from the device
- Reboot device remotely

## Setup

### Linux

- `git clone https://github.com/5E7EN/Kyocera-Diag-Interface.git && cd Kyocera-Diag-Interface`
- `sudo apt install python3-tk adb sg3-utils`
- `pip install -r requirements.txt`

### Windows

1. Install [Python 3.10+](https://www.python.org/downloads/) (ensure "Add to PATH" is checked during install)

2. Install [Minimal ADB and Fastboot](https://androiddatahost.com/wp-content/uploads/Minimal_ADB_Fastboot_v1.4.3.zip) and add to your PATH

3. Install [Zadig](https://zadig.akeo.ie/) (needed for USB driver setup - see step 5)

4. Download [libusb](https://github.com/libusb/libusb/releases/download/v1.0.27/libusb-1.0.27.7z)
    - Extract `VS2022/MS64/dll/libusb-1.0.dll`
    - Place it next to your `python.exe` (likely `%LOCALAPPDATA%\Programs\Python\Python314`)

5. Clone and install dependencies:
    - `git clone https://github.com/5E7EN/Kyocera-Diag-Interface.git`
    - `cd Kyocera-Diag-Interface`
    - `pip install -r requirements.txt`
    - `pip install libusb-package`

    The `libusb-package` pip module provides the libusb-1.0 DLL that PyUSB needs on Windows.

6. **USB driver setup (one-time, required for diag mode):**
    - In an administrator terminal, run the tool - `python main.py`
    - Connect your Kyocera device and switch it to diag mode (the app will handle switching via ADB/CDROM automatically, but once the device appears in diag mode, you need the correct driver)
    - Open Zadig
    - Find the Kyocera diag interface in the dropdown (`KYOCERA_Android (Interface 0)`)
        - USB ID should match: `0482 0A9D 00`
    - Select **WinUSB (...)** as the driver and click **Install Driver**
    - Once installed, disconnect the device and reconnect, then close the app and re-launch it
    - This only needs to be done once per machine

**Please note:** Windows insider builds are not supported by Zadig unless you disable driver signature enforcement.

## Usage

### Windows

Run a terminal (Command Prompt or PowerShell) **as Administrator**, then:

```
python main.py
```

### Linux

```
sudo python3 main.py
```

### Steps

1. Enable USB Debugging on the device (Settings > Developer Options)
2. Connect the device and accept the ADB authorization prompt
3. Click "Detect Device" in the app
4. Use "Switch to Diag Mode" to get full diag access

## Credits

**GUI:** @ClaudeOpus and @5E7EN  
**Scripts & tooling:** @5E7EN and @LeoBuskin

Special thanks to @LeoBuskin for research findings that helped identify the mechanisms used here.

Methods adapted from official, publicly-available Kyocera/Qualcomm tooling and device analysis.

Yes, Claude almost entirely helped with the GUI implementation.  
It also assisted with backend refactoring/modularization to make this production-ready.
