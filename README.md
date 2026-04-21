# FR3 Control GUI (Local-Only)

Tkinter GUI for launching FR3 visual-servo and kinesthetic-teaching tools on the same Linux machine where the robot software runs.

## What Changed In This Branch

This branch removes all remote-control infrastructure:

- no SSH connection flow
- no Paramiko
- no WSL integration
- no `sshpass`
- no X11 forwarding controls (`vcxsrv` / `.xlaunch`)

The app now launches local processes directly with `bash`.

## Main Features

- Local path and launch-argument configuration:
  - visual servo repository path
  - kinesthetic repository path
  - robot IP
  - `eMc` path
  - visual mode (`1` or `2`)
- Start/Stop/Kill controls for:
  - visual servoing
  - kinesthetic GUI
- Local PID-file based signaling (`SIGTERM` / `SIGKILL`)
- Local process/status check
- Last-log viewer
- Scrollable in-app log panel

## Repository Files

- `FR3_control_GUI.py` - main application
- `FR3 Control GUI.bat` - launcher helper (optional)
- `requirements.txt` - dependency list (empty except comment)
- `config.xlaunch` - legacy file, unused in this branch

## Requirements

- Python 3.9+
- `tkinter`
- Linux environment with `bash` and `ps`
- ROS 2 Humble available at:

```bash
/opt/ros/humble/setup.bash
```

- Launch scripts present and executable:
  - `run_visual_servo_combined.sh`
  - `run_gui.sh`

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python FR3_control_GUI.py
```

## Runtime Files

The app uses:

- `/tmp/fr3_visual_servo.pid`
- `/tmp/fr3_kinesthetic_gui.pid`
- `/tmp/fr3_visual_servo.log`
- `/tmp/fr3_kinesthetic.log`

## Typical Flow

1. Start the GUI.
2. Confirm local paths and arguments.
3. Click `Start Visual Servo` and/or `Start Kinesthetic GUI`.
4. Use `Check Local Status` and `Show Last Logs` for diagnostics.
5. Use `Stop` or `Kill` when needed.

## Notes

- The GUI does not auto-stop processes on close.
- Stop/Kill behavior depends on PID-file correctness from the launched shell process.
- If your scripts do not write logs to `/tmp/fr3_*.log`, `Show Last Logs` will report no logs.
