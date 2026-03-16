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
Currently only supports Linux.

### Linux:

```bash
sudo apt install python3-tk adb sg3-utils
pip install -r requirements.txt
```

## Usage

```
sudo python3 main.py
```

1. Enable USB Debugging on the device (Settings > Developer Options)
2. Connect the device and accept the ADB authorization prompt
3. Click "Detect Device" in the app
4. Use "Switch to Diag Mode" to get full diag access

## Credits

**GUI:** @ClaudeOpus and @5E7EN  
**Scripts & tooling:** @5E7EN and @LeoBuskin

Special thanks to @LeoBuskin for research findings that helped identify the mechanisms used here.

Methods adapted from official, publicly-available Kyocera/Qualcomm tooling and device analysis.
