# FR3 Control GUI

Windows Tkinter GUI to connect to a remote Ubuntu machine and launch FR3 visual-servo and kinesthetic-teaching GUIs through `WSL + ssh -Y` with X11 forwarding.

## Validated Environment

This launcher is currently documented and validated for a remote FR3 machine running a Jazzy-based stack.

- Local launcher machine: Windows with WSL + X11 server
- Remote OS: Ubuntu 24.04 LTS
- Remote ROS distro: ROS 2 Jazzy
- Robot: Franka Research 3 (FR3)
- Robot system version used during validation: 5.7.2
- `franka_ros2` workspace version used during validation: `v3.1.1`
- `libfranka` version used during validation: `0.15.3`
- `franka_description` version used during validation: `1.6.1`
- Remote kernel used during validation: `6.12.79-rt17`

Important notes:
- This repo now launches remote tools with `/opt/ros/jazzy/setup.bash`.
- The visual-servo and kinesthetic repositories on the remote machine are expected to be Jazzy-compatible as well.
- The Franka stack versions above matter for an FR3 on system version `5.7.2`.
- A realtime kernel is recommended on the remote Ubuntu machine for smoother robot behavior.

## What This App Does

`FR3_control_GUI.py` uses two paths:

1. A direct Paramiko SSH connection for connection testing and remote shell commands.
2. A WSL-based `sshpass ssh -Y` path for launching remote Linux GUI applications and displaying them on Windows through X11.

The current workflow is:

1. Run this Python GUI on the Windows laptop.
2. Activate the Windows X server from the GUI using the checked-in `config.xlaunch` file.
3. Test the SSH connection to the remote Ubuntu machine.
4. Continue only after both SSH and X11 are ready.
5. When you continue into the control screen, the GUI automatically starts `robot_state_publisher.py` on the remote Ubuntu machine so the LSL stream is available.
6. Launch remote FR3 GUIs from the control screen and display them back on the laptop through X11 forwarding.

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
  - `robot_state_publisher.py`
- Configurable launch arguments for:
  - robot IP
  - `eMc` config path
  - visual mode (`1` or `2`)
- Automatic remote startup of `robot_state_publisher.py` when entering the control screen
- Automatic remote shutdown of `robot_state_publisher.py` when SSH is disconnected or the GUI closes
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
- `FR3 Control GUI.bat` - Windows double-click launcher for the GUI
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
- this repository cloned on the remote machine if `robot_state_publisher.py` will be launched from it
- launch scripts available:
  - `run_visual_servo_combined.sh`
  - `run_gui.sh`
- ROS environment available at:

```bash
/opt/ros/jazzy/setup.bash
```

- Python packages for the publisher available on the remote machine:
  - `rclpy`
  - `sensor_msgs`
  - `pylsl`

Default remote paths used by the GUI:

- `/home/parc/FR3_visual_servo_examples`
- `/home/parc/franka_kinesthetic_teaching_GUI`
- `/home/parc/FR3_control_GUI/robot_state_publisher.py`

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

### 3. Launch the GUI

You can start the app in either of these ways:

```powershell
python FR3_control_GUI.py
```

Or on Windows, just double-click:

```text
FR3 Control GUI.bat
```

### 4. Install or confirm WSL and Ubuntu

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

### 5. Complete first-time Ubuntu setup

Launch Ubuntu and create your Linux username/password when prompted.

Update packages:

```bash
sudo apt update && sudo apt upgrade -y
```

### 6. Install WSL-side tools

From inside WSL:

```bash
sudo apt update
sudo apt install -y openssh-client sshpass x11-apps
```

Or from Windows PowerShell:

```powershell
wsl -d Ubuntu -e bash -lc "sudo apt update && sudo apt install -y openssh-client sshpass x11-apps"
```

### 7. Match the WSL distro name in the app

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

- `source /opt/ros/jazzy/setup.bash`
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
/tmp/fr3_robot_state_publisher.pid
/tmp/fr3_visual_servo.log
/tmp/fr3_kinesthetic.log
/tmp/fr3_robot_state_publisher.log
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
9. The control screen automatically starts `robot_state_publisher.py` and keeps its log in `/tmp/fr3_robot_state_publisher.log`.
10. Use `Check Remote Status` and `Show Last Logs` for troubleshooting.

## Control Screen Behavior

### Start Visual Servo

Launches from WSL using `sshpass ssh -Y` and runs remotely:

- `source /opt/ros/jazzy/setup.bash`
- set ROS library path extension
- `cd <visual_servo_repo>`
- `export MODE=<1|2>`
- write PID to `/tmp/fr3_visual_servo.pid`
- `exec ./run_visual_servo_combined.sh --ip <robot_ip> --eMc <eMc_path>`

### Start Kinesthetic GUI

Launches from WSL using `sshpass ssh -Y` and runs remotely:

- `source /opt/ros/jazzy/setup.bash`
- `cd <kinesthetic_repo>`
- write PID to `/tmp/fr3_kinesthetic_gui.pid`
- `exec ./run_gui.sh`

### Robot State Publisher

When you enter the control screen with both SSH and X11 ready, the GUI runs this on the remote machine:

- checks whether `/tmp/fr3_robot_state_publisher.pid` already points to a live process
- removes stale PID files automatically
- sources ROS 2 from `/opt/ros/jazzy/setup.bash`
- starts `python3 <robot_state_publisher.py>` with `nohup`
- writes logs to `/tmp/fr3_robot_state_publisher.log`

When you disconnect SSH or close the GUI, the app sends `SIGTERM` to the publisher PID if it was started through the tracked PID file.

### Optional Robot State API

This repo also includes `robot_state_api.py`, a small local HTTP server intended to run on the robot computer. It lets the real robot-control applications publish the four LSL flags explicitly:

- `visual_servo_active`
- `kt_active`
- `arm_moving`
- `gripper_moving`

Default endpoint:

```text
http://127.0.0.1:8765/state
```

Example update:

```bash
curl -X POST http://127.0.0.1:8765/state \
  -H "Content-Type: application/json" \
  -d '{"visual_servo_active": 1, "arm_moving": 1, "ttl_sec": 0.5}'
```

The GUI now starts `robot_state_api.py` automatically on the robot computer alongside `robot_motion_monitor.py` and `robot_state_publisher.py` when you enter the control screen.

`robot_state_publisher.py` uses API values when they are present, but it still keeps the older process/ROS-topic heuristics active as fallback so visual-servo and kinesthetic activity do not disappear just because the API is running.

### Robot Motion Monitor

`robot_motion_monitor.py` is a sidecar process in this repo that discovers ROS 2 `sensor_msgs/msg/JointState` topics dynamically, estimates arm/gripper motion, and posts those motion flags into `robot_state_api.py`.

This keeps the LSL publisher itself simple:

- `robot_motion_monitor.py` observes motion
- `robot_state_api.py` stores explicit state
- `robot_state_publisher.py` publishes the LSL stream

### Current LSL Status

Current observed behavior of the LSL stream:

- `kt_active` works for kinesthetic teaching
- kinesthetic arm-motion detection works when the kinesthetic stack brings up ROS joint-state topics
- kinesthetic gripper-state handling is partially working through ROS and gripper action status observation
- `visual_servo_active` works from the tracked visual-servo PID/process state
- true arm-motion detection for visual servo is still not implemented in a reliable way

Why visual-servo arm motion is still unresolved:

- the visual-servo application moves the robot through ViSP + `libfranka`
- in the tested setup, visual servo does not publish usable ROS joint-state topics for this repo to observe
- because of that, the current ROS-based `robot_motion_monitor.py` cannot infer `arm_moving` during visual servo

Things that were tried and did not work:

- inferring visual-servo arm motion from ROS `/joint_states`
  - no usable motion messages were present during visual servo
- inferring motion from visual-servo stdout/log text
  - this was noisy and produced incorrect spikes instead of true motion state
- using unrelated Python Franka packages as a direct state backend
  - the installed `franky` package on the robot computer did not expose a robot API
- launching a separate external `libfranka` sidecar client
  - this interfered with the real visual-servo process and caused `franka::NetworkException` / connection loss

Recommended next step for visual servo:

- update the visual-servo application or its wrapper so the same process that already owns `libfranka` also emits `arm_moving`

That is the safest correct approach because:

- it does not depend on ROS topics that are missing during visual servo
- it does not require a second competing `libfranka` connection
- it lets the process that already knows the true robot motion publish the state directly into `robot_state_api.py`

### Stop / Kill Buttons

- `Stop` sends `SIGTERM` to the PID in the corresponding `/tmp/*.pid`
- `Kill` sends `SIGKILL` to the PID in the corresponding `/tmp/*.pid`
- if the PID is missing or stale, the GUI reports that clearly in the log

### Check Remote Status

Shows:

- PID file contents, or `missing`
- matching process lines from `ps -ef`
- includes `robot_state_publisher.py`

### Show Last Logs

Reads:

- `/tmp/fr3_visual_servo.log` tail output
- `/tmp/fr3_kinesthetic.log` tail output
- `/tmp/fr3_robot_state_publisher.log` tail output

### Other Buttons

- `Back` returns to the connection/config page
- `Disconnect` closes the Paramiko SSH session
- closing the window disconnects the Paramiko SSH session only and does not automatically stop remote processes

## Defaults in Code

- Host: `192.168.0.242`
- Port: `22`
- User: `parc`
- WSL distro: `Ubuntu`
- Visual repo: `/home/parc/FR3_visual_servo_examples`
- Kinesthetic repo: `/home/parc/franka_kinesthetic_teaching_GUI`
- State publisher: `/home/parc/FR3_control_GUI/robot_state_publisher.py`
- Robot IP: `172.16.0.2`
- `eMc`: `config/eMc.yaml`
- Visual mode: `1`

## Known Notes

- The app requires `sshpass` in WSL for GUI launch actions.
- Password-based SSH is currently used for the WSL launch path.
- X11 status is checked continuously by polling for `vcxsrv.exe`.
- If VcXsrv is closed manually in Windows, the GUI should return to `X11 inactive` automatically.
- `Continue` is blocked unless both SSH and X11 are ready.
- Entering the control screen also assumes the remote machine can run `python3 robot_state_publisher.py` after sourcing ROS 2.
- Closing the app disconnects the Paramiko SSH client and stops the tracked `robot_state_publisher.py` process, but it does not automatically stop the visual-servo or kinesthetic processes if they are already running.
