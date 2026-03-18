# FR3 Control GUI

Windows Tkinter GUI to connect to a remote Ubuntu machine and launch FR3 visual-servo and kinesthetic-teaching GUIs through `WSL + ssh -Y` (X11 forwarding).

## What This App Does

`FR3_control_GUI.py` has two paths:

1. `paramiko` SSH session (for connection test, stop/kill, status, logs).
2. `wsl.exe` launch path using `sshpass ssh -Y` (for remote GUI windows displayed on your Windows laptop).

Remote GUIs are not rendered by Tkinter itself. They are rendered by your Windows X server via X11 forwarding.

## Repository Files

- `FR3_control_GUI.py`: main application
- `requirements.txt`: Python dependency (`paramiko`)

## Prerequisites

### Windows laptop

- Windows with WSL enabled
- One Ubuntu distro installed in WSL (default expected name: `Ubuntu`)
- Python 3.9+ on Windows (with Tkinter available)
- Network access to remote Ubuntu host
- An X server running on Windows (for forwarded Linux GUIs)

### Local WSL Ubuntu distro

Install required tools:

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

## X Server Setup (Important)

The app builds this in WSL before launching remote GUI commands:

```bash
export DISPLAY=$(grep nameserver /etc/resolv.conf | awk '{print $2}'):0.0
```

So your Windows X server must be running and accepting connections on display `:0`.

### Recommended workflow

1. Install an X server on Windows (for example VcXsrv or Xming).
2. Start it before launching `FR3_control_GUI.py`.
3. If the X server has access control options, allow local/private network connections as needed for your setup.

### Quick X11 validation from WSL

Run:

```powershell
wsl -d Ubuntu -e bash -lc "export DISPLAY=\$(grep nameserver /etc/resolv.conf | awk '{print \$2}'):0.0; xclock"
```

If `xclock` appears on Windows, local X11 path works.

### End-to-end SSH X11 validation

Run:

```powershell
wsl -d Ubuntu -e bash -lc "export DISPLAY=\$(grep nameserver /etc/resolv.conf | awk '{print \$2}'):0.0; ssh -Y <user>@<remote-host> xclock"
```

If remote `xclock` appears on Windows, your X11 forwarding path is ready for this GUI.

## Start the Application

From this repo on Windows:

```powershell
python FR3_control_GUI.py
```

## How To Operate the GUI

### 1) Connection page

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

- `WSL does not have sshpass installed yet`: install `sshpass` in the selected distro.
- Start buttons do nothing / remote GUI never appears: X server is not running or `DISPLAY` route is blocked.
- SSH test succeeds but remote GUI fails: verify `ssh -Y` path manually with remote `xclock`.
- Stop/Kill says PID file missing: process may not have created PID file or already exited.
