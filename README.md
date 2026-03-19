# FR3 Control GUI

Windows Tkinter GUI to connect to a remote Ubuntu machine and launch FR3 visual-servo and kinesthetic-teaching GUIs through `WSL + ssh -Y` with X11 forwarding.

## What This App Does

`FR3_control_GUI.py` uses two paths:

1. A direct Paramiko SSH connection for connection testing and remote shell commands.
2. A WSL-based `sshpass ssh -Y` path for launching remote Linux GUI applications and displaying them on Windows through X11.

The current workflow is:

1. Run this Python GUI on the Windows laptop.
2. Activate the Windows X server from the GUI using the checked-in `config.xlaunch` file.
3. Test the SSH connection to the remote Ubuntu machine.
4. Continue only after both SSH and X11 are ready.
5. Launch remote FR3 GUIs from the control screen and display them back on the laptop through X11 forwarding.

Remote GUIs are not rendered by Tkinter itself. They are rendered by your Windows X server via X11 forwarding.

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
- `Disconnect SSH` button on the first screen
- `Continue` button that only enables when:
  - SSH is connected
  - X11 is active
- Automatic X11 polling so manual VcXsrv closes are detected by the GUI
- Configurable remote repository paths for:
  - visual servo project
  - kinesthetic teaching project
- Configurable launch arguments for:
  - robot IP
  - `eMc` config path
  - visual mode (`1` or `2`)
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

## Repository Files

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

- The script sets `DISPLAY` inside WSL using `/etc/resolv.conf`, which matches a common X11-on-Windows setup.
- This repo includes a saved `config.xlaunch` file that the GUI uses when you click `Activate X11`.
- The GUI checks for `vcxsrv.exe` to decide whether X11 is currently active.

### On the Local WSL Ubuntu Distro

- `bash`
- `ssh`
- `sshpass`
- `x11-apps` for quick X11 testing

Install the WSL-side tools with:

```bash
sudo apt update
sudo apt install -y openssh-client sshpass x11-apps
```

`x11-apps` is useful for quick tests such as `xclock` or `xeyes`.

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

Default remote paths used by the GUI:

- `/home/parc/FR3_visual_servo_examples`
- `/home/parc/franka_kinesthetic_teaching_GUI`

## Installation

### 1. Clone and enter the repo on Windows

```powershell
git clone <your-repo-url>
cd FR3_control_GUI
```

### 2. Install Python dependency on Windows

```powershell
python -m pip install -r requirements.txt
```

### 3. Install or confirm WSL and Ubuntu

If WSL is not installed yet:

```powershell
wsl --install
```

Check installed distro names:

```powershell
wsl --list --verbose
```

Use the exact distro name from this output in the GUI `WSL Distro` field.

If Ubuntu is not installed yet:

```powershell
wsl --install -d Ubuntu
```

### 4. Complete first-time Ubuntu setup

Launch Ubuntu and create your Linux username/password when prompted.

Update packages:

```bash
sudo apt update && sudo apt upgrade -y
```

### 5. Install WSL-side tools

From inside WSL:

```bash
sudo apt update
sudo apt install -y openssh-client sshpass x11-apps
```

Or from Windows PowerShell:

```powershell
wsl -d Ubuntu -e bash -lc "sudo apt update && sudo apt install -y openssh-client sshpass x11-apps"
```

### 6. Match the WSL distro name in the app

The GUI default is:

```text
Ubuntu
```

If your installed distro has a different name, enter that exact name in the `WSL Distro` field.

## X Server Setup

The app builds this in WSL before launching remote GUI commands:

```bash
export DISPLAY=$(grep nameserver /etc/resolv.conf | awk '{print $2}'):0.0
```

So your Windows X server must be running and accepting connections on display `:0`.

### Install and launch VcXsrv/XLaunch on Windows

1. Download VcXsrv from:
   - https://github.com/ArcticaProject/vcxsrv/releases
2. Download the latest installer asset, usually named like `vcxsrv-64.*.installer.exe`.
3. Run the installer with default options.
4. Keep the repo's `config.xlaunch` file in place.
5. Use the GUI `Activate X11` button to launch the saved XLaunch configuration.

Typical XLaunch settings for this workflow:

- Multiple windows
- Start no client
- Disable access control for trusted local workflows

The GUI checks for `vcxsrv.exe` continuously, so if X11 is closed manually on Windows, the app should return to `X11 inactive`.

### Quick X11 validation from WSL

Run:

```powershell
wsl -d Ubuntu -e bash -lc "export DISPLAY=\$(grep nameserver /etc/resolv.conf | awk '{print \$2}'):0.0; xclock"
```

If `xclock` appears on Windows, the local X11 path works.

### End-to-end SSH X11 validation

After VcXsrv is running, verify forwarded remote GUI support by launching a lightweight X11 app from the remote Ubuntu machine through SSH.

Useful checks:

- confirm the GUI shows `X11 active`
- confirm the SSH test succeeds
- confirm a forwarded remote GUI opens on Windows

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

### Stop and Kill Behavior

- `Stop` sends `SIGTERM`
- `Kill` sends `SIGKILL`
- the GUI validates the PID before signaling it
- if the PID file is stale, the GUI removes it and reports that cleanup in the log

## Runtime Files Used on the Remote Machine

The script currently uses these files on the remote Ubuntu computer:

```text
/tmp/fr3_visual_servo.pid
/tmp/fr3_kinesthetic_gui.pid
/tmp/fr3_visual_servo.log
/tmp/fr3_kinesthetic.log
```

The status and log buttons read from these locations.

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

## Control Screen Behavior

### Start Visual Servo

Launches from WSL using `sshpass ssh -Y` and runs remotely:

- `source /opt/ros/humble/setup.bash`
- set ROS library path extension
- `cd <visual_servo_repo>`
- `export MODE=<1|2>`
- write PID to `/tmp/fr3_visual_servo.pid`
- `exec ./run_visual_servo_combined.sh --ip <robot_ip> --eMc <eMc_path>`

### Start Kinesthetic GUI

Launches from WSL using `sshpass ssh -Y` and runs remotely:

- `source /opt/ros/humble/setup.bash`
- `cd <kinesthetic_repo>`
- write PID to `/tmp/fr3_kinesthetic_gui.pid`
- `exec ./run_gui.sh`

### Stop / Kill Buttons

- `Stop` sends `SIGTERM` to the PID in the corresponding `/tmp/*.pid`
- `Kill` sends `SIGKILL` to the PID in the corresponding `/tmp/*.pid`
- if the PID is missing or stale, the GUI reports that clearly in the log

### Check Remote Status

Shows:

- PID file contents, or `missing`
- matching process lines from `ps -ef`

### Show Last Logs

Reads:

- `/tmp/fr3_visual_servo.log` tail output
- `/tmp/fr3_kinesthetic.log` tail output

### Other Buttons

- `Back` returns to the connection/config page
- `Disconnect` closes the Paramiko SSH session
- closing the window disconnects the Paramiko SSH session only and does not automatically stop remote processes

## Defaults in Code

- Host: `192.168.0.121`
- Port: `22`
- User: `parc`
- WSL distro: `Ubuntu`
- Visual repo: `/home/parc/FR3_visual_servo_examples`
- Kinesthetic repo: `/home/parc/franka_kinesthetic_teaching_GUI`
- Robot IP: `172.16.0.2`
- `eMc`: `config/eMc.yaml`
- Visual mode: `1`

## Known Notes

- The app requires `sshpass` in WSL for GUI launch actions.
- Password-based SSH is currently used for the WSL launch path.
- X11 status is checked continuously by polling for `vcxsrv.exe`.
- If VcXsrv is closed manually in Windows, the GUI should return to `X11 inactive` automatically.
- `Continue` is blocked unless both SSH and X11 are ready.
- Closing the app disconnects the Paramiko SSH client, but it does not automatically stop remote processes that are already running.
