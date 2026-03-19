# FR3 Control GUI

Windows Tkinter GUI to connect to a remote Ubuntu machine and launch FR3 visual-servo and kinesthetic-teaching GUIs through `WSL + ssh -Y` (X11 forwarding).

## What This App Does

`FR3_control_GUI.py` has two paths:

1. Run this Python GUI on the Windows laptop.
2. The GUI uses `paramiko` for SSH connection testing and remote shell commands.
3. For GUI-based remote apps, the GUI starts `wsl.exe` and runs `sshpass ssh -Y` from the local WSL Ubuntu distro to the remote Ubuntu computer.
4. The GUI can launch the checked-in `config.xlaunch` file to start the Windows X11 server.
5. The remote Ubuntu machine launches the FR3 GUIs and displays them back on the laptop through X11 forwarding.

Remote GUIs are not rendered by Tkinter itself. They are rendered by your Windows X server via X11 forwarding.

## Repository Files

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

## Prerequisites

- `FR3_control_GUI.py` - main application
- `requirements.txt` - Python dependency list
- `config.xlaunch` - saved XLaunch configuration used by `Activate X11`

- Windows with WSL enabled
- One Ubuntu distro installed in WSL (default expected name: `Ubuntu`)
- Python 3.9+ on Windows (with Tkinter available)
- Network access to remote Ubuntu host
- An X server running on Windows (for forwarded Linux GUIs)

### Local WSL Ubuntu distro

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
sudo apt install -y openssh-client sshpass x11-apps
```

`x11-apps` is for quick X11 testing (`xclock`, `xeyes`).

### Remote Ubuntu machine

- SSH server reachable from laptop
- FR3 repos present
- Scripts available and executable:
  - `run_visual_servo_combined.sh`
  - `run_gui.sh`
- ROS setup present at `/opt/ros/humble/setup.bash`

Default repo paths used by GUI:

- `/home/parc/FR3_visual_servo_examples`
- `/home/parc/franka_kinesthetic_teaching_GUI`

## Installation

### 1. Clone and enter repo (Windows)

```powershell
git clone <your-repo-url>
cd FR3_control_GUI
```

### 2. Install Python dependency (Windows)

```powershell
python -m pip install -r requirements.txt
```

### 3. Install/confirm WSL + Ubuntu

If WSL is not installed:

```powershell
wsl --install
```

Check distro names:

```powershell
wsl --list --verbose
```

Use the exact distro name from this output in the GUI `WSL Distro` field.

### 4. Install WSL-side tools

```powershell
wsl -d Ubuntu -e bash -lc "sudo apt update && sudo apt install -y openssh-client sshpass x11-apps"
```

## X Server Setup

The app builds this in WSL before launching remote GUI commands:

```bash
export DISPLAY=$(grep nameserver /etc/resolv.conf | awk '{print $2}'):0.0
```

So your Windows X server must be running and accepting connections on display `:0`.

### Download and install on Windows

1. Download VcXsrv from:
   - https://github.com/ArcticaProject/vcxsrv/releases
2. Download the latest installer asset (usually `vcxsrv-64.*.installer.exe`).
3. Run installer with default options.
4. Launch `XLaunch` from Start Menu.
5. In XLaunch, use these typical settings:
   - Multiple windows
   - Start no client
   - Disable access control (common for local WSL/X11 workflows on trusted networks)
6. Finish and keep VcXsrv running before launching `FR3_control_GUI.py`.

### Quick X11 validation from WSL

Run:

```powershell
wsl -d Ubuntu -e bash -lc "export DISPLAY=\$(grep nameserver /etc/resolv.conf | awk '{print \$2}'):0.0; xclock"
```

If `xclock` appears on Windows, local X11 path works.

### End-to-end SSH X11 validation

Run:

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

If remote `xclock` appears on Windows, your X11 forwarding path is ready for this GUI.

## Start the Application

From this repo on Windows:

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

## How To Operate the GUI

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

Fill in:

- `Host`, `Port`, `Username`, `Password`
- `WSL Distro`
- `Visual Servo Repo`
- `Kinesthetic Repo`
- `Robot IP`
- `eMc Path`
- `Visual Mode` (`1` or `2`)

Click `Test Connection`.

What it checks:

- Paramiko SSH login and command execution (`echo SSH_OK && hostname && pwd`)
- Whether `sshpass` exists in WSL

Then click `Continue` to enter control interface.

### 2) Control page

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

### Stop / Kill buttons

- `Stop` sends `SIGTERM` to PID in corresponding `/tmp/*.pid`
- `Kill` sends `SIGKILL` to PID in corresponding `/tmp/*.pid`

### Check Remote Status

Shows:

- PID file contents (or missing)
- matching process lines from `ps -ef`

### Show Last Logs

Reads:

- `/tmp/fr3_visual_servo.log` (tail 30)
- `/tmp/fr3_kinesthetic.log` (tail 30)

### Other buttons

- `Back`: return to connection/config page
- `Disconnect`: closes Paramiko SSH session
- Closing window: disconnects Paramiko session only (does not auto-stop remote processes)

## Runtime Files on Remote

- `/tmp/fr3_visual_servo.pid`
- `/tmp/fr3_kinesthetic_gui.pid`
- `/tmp/fr3_visual_servo.log`
- `/tmp/fr3_kinesthetic.log`

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

## Troubleshooting

## Known Notes

- The app requires `sshpass` in WSL for GUI launch actions.
- Password-based SSH is currently used for the WSL launch path.
- `Stop` sends `SIGTERM`; `Kill` sends `SIGKILL`.
- X11 status is checked continuously by polling for `vcxsrv.exe`.
- If VcXsrv is closed manually in Windows, the GUI should return to `X11 inactive` automatically.
- `Back` returns to the login/config page.
- `Continue` is blocked unless both SSH and X11 are ready.
- Closing the app disconnects the Paramiko SSH client, but it does not automatically stop remote processes that are already running.
