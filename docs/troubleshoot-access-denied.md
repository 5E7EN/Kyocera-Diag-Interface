# Troubleshooting: Access Denied in Diag Mode

## Symptom
Application returns "Access Denied" error when connecting in diagnostic mode.

## Common Causes

### 1. Insufficient Permissions
- Run as Administrator (Windows)
- Use `sudo` (Linux/macOS)

### 2. Driver Not Installed
- Install Kyocera diagnostic driver from manufacturer CD
- Check Device Manager for unrecognized devices

### 3. Wrong Port/Interface
- Verify correct COM port in settings
- Try USB 2.0 port instead of USB 3.0

### 4. Firewall Blocking
- Add exception for application in Windows Firewall
- Temporarily disable antivirus for testing

## Quick Fix Steps
1. Right-click -> Run as Administrator
2. Check cable connection (firmly seated)
3. Restart both PC and device
4. Try different USB port
5. Disable firewall temporarily