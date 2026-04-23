# FR3 Control GUI

This repository contains a small local control/monitoring toolkit for an FR3 setup:

- `FR3_control_GUI.py`: Tkinter launcher for starting and stopping the local visual-servo and kinesthetic-teaching applications
- `robot_state_api.py`: local HTTP API for robot-state flags
- `robot_motion_monitor.py`: ROS 2 sidecar that detects arm/gripper motion and pushes state into the API
- `robot_state_publisher.py`: ROS 2 + LSL publisher that exposes six binary robot-state channels

The code is local-first. The GUI launches processes on the same Linux machine that has the robot software installed.

## Repository Contents

- `FR3_control_GUI.py` - main Tkinter GUI
- `robot_state_api.py` - local HTTP state service on `127.0.0.1:8765` by default
- `robot_motion_monitor.py` - ROS 2 node that discovers `JointState` and gripper status topics and updates the state API
- `robot_state_publisher.py` - ROS 2 node that publishes an LSL stream named `FR3_State`
- `FR3 Control GUI.desktop` - Linux desktop launcher
- `FR3 Control GUI.bat` - Windows launcher helper for a specific local Conda environment path
- `config.xlaunch` - legacy X11 launcher config, not used by the Python code in this repo
- `requirements.txt` - minimal Python dependency note for the GUI

## GUI Features

`FR3_control_GUI.py` provides:

- editable launch settings for:
  - visual-servo repository path
  - kinesthetic-teaching repository path
  - robot IP
  - `eMc` path
  - visual mode (`1` or `2`)
- start, stop, and kill controls for:
  - visual servo
  - kinesthetic GUI
- local process launching through `bash -lc`
- automatic sourcing of `/opt/ros/humble/setup.bash` before launching the tools
- a scrollable in-app log panel with live subprocess output
- local status inspection via PID files and `ps`
- log inspection via `tail` on the expected log files

Window title: `FR3 Local Launcher`

## Expected External Scripts

The GUI expects these scripts to exist in the configured repositories:

- visual-servo repo: `./run_visual_servo_combined.sh`
- kinesthetic repo: `./run_gui.sh`

When starting visual servo, the GUI runs the equivalent of:

```bash
source /opt/ros/humble/setup.bash
cd <visual_dir>
export LD_LIBRARY_PATH=/opt/ros/humble/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH
export MODE=<1-or-2>
exec ./run_visual_servo_combined.sh --ip <robot_ip> --eMc <emc_path>
```

When starting the kinesthetic GUI, it runs:

```bash
source /opt/ros/humble/setup.bash
cd <kinesthetic_dir>
exec ./run_gui.sh
```

## Runtime Files

The GUI uses these local files under `/tmp`:

- `/tmp/fr3_visual_servo.pid`
- `/tmp/fr3_kinesthetic_gui.pid`
- `/tmp/fr3_visual_servo.log`
- `/tmp/fr3_kinesthetic.log`

The PID files are written by the launcher shell before `exec`. Stop and kill actions signal the PID stored in those files.

The log viewer reads the `/tmp/fr3_*.log` files if the launched applications write to them. The GUI itself does not create those log files.

## Robot State API

`robot_state_api.py` runs a local HTTP server with:

- `GET /health`
- `GET /state`
- `POST /state`

Default bind address:

- host: `127.0.0.1`
- port: `8765`

Environment variables:

- `FR3_STATE_API_HOST`
- `FR3_STATE_API_PORT`

State fields:

- `visual_servo_active`
- `kt_active`
- `teaching_active`
- `running_active`
- `arm_moving`
- `gripper_moving`

`POST /state` accepts partial updates and an optional `ttl_sec`. If a TTL is supplied, updated fields fall back to `null` after expiry unless refreshed.

Example:

```json
{
  "visual_servo_active": 1,
  "arm_moving": 1,
  "ttl_sec": 0.5
}
```

## Robot Motion Monitor

`robot_motion_monitor.py` is a ROS 2 node that:

- discovers `sensor_msgs/msg/JointState` topics dynamically
- discovers gripper-related `action_msgs/msg/GoalStatusArray` status topics
- infers `arm_moving` and `gripper_moving`
- pushes active motion flags to `robot_state_api.py`

Current behavior:

- posts to `http://127.0.0.1:8765/state`
- only sends fields that are currently active, with a short TTL
- uses joint velocity thresholds first, then falls back to position deltas only when velocity data is unavailable
- logs periodic diagnostics about discovered topics and inferred motion state

Python dependencies for this script come from the ROS 2 environment, not from `requirements.txt`.

## Robot State Publisher

`robot_state_publisher.py` is a ROS 2 node that publishes an LSL stream:

- stream name: `FR3_State`
- stream type: `RobotState`
- channel count: `6`
- nominal rate: `50 Hz`
- channel labels:
  - `visual_servo_active`
  - `kt_active`
  - `teaching_active`
  - `running_active`
  - `arm_moving`
  - `gripper_moving`

It combines:

- local process matching from `ps`
- motion inferred from robot topics and explicit state updates
- state data from `robot_state_api.py` when available

Current integration notes:

- `teaching_active` and `running_active` are intended to come from explicit updates produced by the kinesthetic GUI workflow.
- visual-servo `arm_moving` can be published directly by the C++ visual-servo controller into `robot_state_api.py`, which is more reliable than ROS-side inference for the ViSP/libfranka path.

This script requires ROS 2 Python packages and `pylsl`.

## Requirements

For the GUI only:

- Python 3
- `tkinter`
- `bash`
- `ps`
- Linux machine with `/opt/ros/humble/setup.bash`

For the ROS 2 state tools:

- ROS 2 Python environment with `rclpy`
- ROS message packages used by the scripts
- `pylsl` for `robot_state_publisher.py`

`requirements.txt` currently reflects only the GUI and does not list the ROS 2 or LSL dependencies for the sidecar scripts.

## Running

Start the GUI:

```bash
python3 FR3_control_GUI.py
```

Start the local state API:

```bash
python3 robot_state_api.py
```

Start the motion monitor in a ROS 2 environment:

```bash
python3 robot_motion_monitor.py
```

Start the LSL publisher in a ROS 2 environment:

```bash
python3 robot_state_publisher.py
```

On Linux, `FR3 Control GUI.desktop` can be used as a desktop launcher. Its current `Exec` command is `python3 FR3_control_GUI.py` with `Path=/home/parc/FR3_control_GUI`.

`FR3 Control GUI.bat` is a Windows-only helper that tries to launch `FR3_control_GUI.py` from a specific Conda environment under `C:\Users\Investment\miniconda3\envs\computer_vision`. That path is hard-coded.

## Typical GUI Flow

1. Launch `FR3_control_GUI.py`.
2. Confirm the repository paths and launch arguments.
3. Start visual servo and/or the kinesthetic GUI.
4. Use `Check Local Status` to inspect PID files and matching processes.
5. Use `Show Last Logs` if the launched tools write logs to the expected `/tmp` files.
6. Use `Stop` for `SIGTERM` or `Kill` for `SIGKILL`.

## Notes and Limitations

- Opening and closing the Tkinter window now performs aggressive cleanup of the managed background processes used by this toolkit.
- Stop/kill behavior depends on the PID file matching the process that should be signaled.
- The GUI stores the shell PID just before `exec`; stale PID files are removed when detected.
- `check_local_status()` matches processes using:
  - `servoFrankaIBVS_combined`
  - `run_visual_servo_combined.sh`
  - `franka_teach`
  - `run_gui.sh`
- `robot_state_publisher.py` now discovers `JointState` topics dynamically instead of relying on a single hard-coded `/joint_states` subscription.
- `config.xlaunch` is present but unused by the current Python code.
