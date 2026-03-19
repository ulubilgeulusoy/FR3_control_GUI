# FR3 Control GUI

Tkinter desktop application for launching and managing FR3 visual servoing and kinesthetic teaching tools from a Windows laptop through WSL Ubuntu to a remote Ubuntu machine over SSH.

## Overview

The current workflow is:

1. Run this Python GUI on the Windows laptop.
2. The GUI uses `paramiko` for SSH connection testing and remote shell commands.
3. For GUI-based remote apps, the GUI starts `wsl.exe` and runs `sshpass ssh -Y` from the local WSL Ubuntu distro to the remote Ubuntu computer.
4. The GUI can launch the checked-in `config.xlaunch` file to start the Windows X11 server.
5. The remote Ubuntu machine launches the FR3 GUIs and displays them back on the laptop through X11 forwarding.

This lets the laptop act as the operator station while the FR3-related software stays on the remote Linux machine.

## Current Features

- SSH login screen with saved default values for host, port, username, and WSL distro
- Login-screen X11 controls using the repository's `config.xlaunch`
- `Activate X11` and `Disconnect X11` buttons on the first screen
- Live X11 status indicator with color feedback:
  - green when active
  - red when inactive
- Live SSH status indicator with color feedback:
  - green when connected
  - red when disconnected
- Configurable remote repository paths for:
  - visual servo project
  - kinesthetic teaching project
- Configurable launch arguments for:
  - robot IP
  - `eMc` config path
  - visual mode (`1` or `2`)
- `Test Connection` button
- `Disconnect SSH` button on the first screen
- `Continue` button that only enables when:
  - SSH is connected
  - X11 is active
- Start, stop, and kill controls for:
  - visual servoing
  - kinesthetic teaching GUI
- Improved remote stop/kill handling:
  - validates PID files before signaling
  - removes stale PID files automatically
- Remote status check for PID files and matching processes
- Last-log viewer for both tools
- Scrollable log panel inside the app
- Clean SSH disconnect on exit
- Automatic X11 polling so manual VcXsrv closes are detected by the GUI

## Files

- `FR3_control_GUI.py` - main application
- `requirements.txt` - Python dependency list
- `config.xlaunch` - saved XLaunch configuration used by `Activate X11`

## Python Requirements

- Python 3.9 or newer recommended
- `tkinter` available in the local Python installation
- packages from `requirements.txt`

Install the Python dependency with:

```bash
pip install -r requirements.txt
```

## System Requirements

### On the Windows Laptop

- Windows with WSL installed
- A working Ubuntu distro in WSL
- Python installed on Windows
- Network access to the remote Ubuntu machine
- VcXsrv/XLaunch installed so `.xlaunch` files can be opened on Windows
- X11 display support for forwarded Linux GUIs

Notes:

- The script currently sets `DISPLAY` inside WSL using `/etc/resolv.conf`, which matches the common X11-on-Windows setup.
- This repo includes a saved `config.xlaunch` file that the GUI uses when you click `Activate X11`.
- The GUI checks for `vcxsrv.exe` to decide whether X11 is currently active.

### On the Local WSL Ubuntu Distro

- `bash`
- `ssh`
- `sshpass`

Install the WSL-side tools with:

```bash
sudo apt update
sudo apt install openssh-client sshpass -y
```

### On the Remote Ubuntu Machine

- SSH server reachable from the laptop
- FR3 repositories already cloned
- launch scripts available:
  - `run_visual_servo_combined.sh`
  - `run_gui.sh`
- ROS environment available at:

```bash
/opt/ros/humble/setup.bash
```

The current default remote paths in the script are:

```text
/home/parc/FR3_visual_servo_examples
/home/parc/franka_kinesthetic_teaching_GUI
```

## WSL Installation Setup

If WSL is not installed on the laptop yet, install it first.

### 1. Install WSL

Open PowerShell as Administrator and run:

```powershell
wsl --install
```

Then reboot if Windows asks you to.

### 2. Install or Confirm an Ubuntu Distro

List installed distros:

```powershell
wsl --list --verbose
```

If Ubuntu is not installed yet, install one of the Ubuntu distros from Microsoft Store or with:

```powershell
wsl --install -d Ubuntu
```

### 3. Complete First-Time Ubuntu Setup

Launch Ubuntu and create your Linux username/password when prompted.

Update packages:

```bash
sudo apt update && sudo apt upgrade -y
```

### 4. Install SSH Tools in WSL

Inside the WSL Ubuntu terminal:

```bash
sudo apt update
sudo apt install openssh-client sshpass -y
```

### 5. Prepare X11 Display Support

Because the script uses `ssh -Y` and sets `DISPLAY`, make sure your laptop can display forwarded Linux GUIs.

Typical setup:

- install VcXsrv/XLaunch on Windows
- keep `config.xlaunch` in this repo
- use the GUI's `Activate X11` button to launch it
- allow local network access if your X server requires it
- verify a forwarded Linux GUI can open on the laptop

### 6. Match the WSL Distro Name in the App

The GUI default is:

```text
Ubuntu
```

If your installed distro has a different name, enter that exact name in the `WSL Distro` field.

## Remote Launch Behavior

### Visual Servo Start

The app starts visual servoing by running, on the remote Ubuntu machine:

- `source /opt/ros/humble/setup.bash`
- exports ROS library path additions
- changes into the visual servo repository
- exports `MODE`
- stores a PID in `/tmp/fr3_visual_servo.pid`
- runs:

```bash
./run_visual_servo_combined.sh --ip <robot_ip> --eMc <eMc_path>
```

### Kinesthetic Start

The app starts kinesthetic teaching by:

- changing into the kinesthetic repository
- storing a PID in `/tmp/fr3_kinesthetic_gui.pid`
- running:

```bash
./run_gui.sh
```

## Runtime Files Used on the Remote Machine

The script currently uses these files on the remote Ubuntu computer:

```text
/tmp/fr3_visual_servo.pid
/tmp/fr3_kinesthetic_gui.pid
/tmp/fr3_visual_servo.log
/tmp/fr3_kinesthetic.log
```

The status and log buttons read from these locations.

Stop and kill actions now validate the PID first. If the PID file is stale, the GUI removes it and reports that cleanup in the log.

## How To Run

From the project folder on Windows:

```bash
python FR3_control_GUI.py
```

## Typical Operator Flow

1. Launch the GUI with Python on Windows.
2. Fill in:
   - remote host
   - port
   - username
   - password
   - WSL distro name
   - remote repository paths
   - robot IP
   - `eMc` path
   - visual mode
3. Click `Activate X11`.
4. Confirm the X11 status shows `X11 active` in green.
5. Click `Test Connection`.
6. Confirm the SSH status shows connected in green and review the `sshpass` check dialog.
7. Once both SSH and X11 are ready, click `Continue`.
8. Use the control screen to start or stop the FR3 tools.
9. Use `Check Remote Status` and `Show Last Logs` for troubleshooting.

## Default Values in the Current Script

- SSH host: `192.168.0.121`
- SSH port: `22`
- SSH username: `parc`
- WSL distro: `Ubuntu`
- visual servo repo: `/home/parc/FR3_visual_servo_examples`
- kinesthetic repo: `/home/parc/franka_kinesthetic_teaching_GUI`
- robot IP: `172.16.0.2`
- `eMc` path: `config/eMc.yaml`
- visual mode: `1`

Update these in the GUI if your environment differs.

## Known Notes

- The app requires `sshpass` in WSL for GUI launch actions.
- Password-based SSH is currently used for the WSL launch path.
- `Stop` sends `SIGTERM`; `Kill` sends `SIGKILL`.
- X11 status is checked continuously by polling for `vcxsrv.exe`.
- If VcXsrv is closed manually in Windows, the GUI should return to `X11 inactive` automatically.
- `Back` returns to the login/config page.
- `Continue` is blocked unless both SSH and X11 are ready.
- Closing the app disconnects the Paramiko SSH client, but it does not automatically stop remote processes that are already running.
