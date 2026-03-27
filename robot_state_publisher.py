#!/usr/bin/env python3
"""
robot_state_publisher.py

Publishes a simple binary robot-state LSL stream from the Ubuntu robot computer.

Channels:
    0: visual_servo_active
    1: kt_active
    2: arm_moving
    3: gripper_moving

Current logic:
- visual_servo_active: 1 if a matching visual-servo process is running
- kt_active: 1 if a matching kinesthetic-teaching process is running
- arm_moving: 1 if robot joint velocity norm is above threshold
- gripper_moving: 1 if gripper joint velocity/position change is above threshold

Notes:
- This version uses ROS 2 /joint_states for motion detection.
- You will likely need to adjust process patterns and gripper joint names.
- LSL timestamps are handled by pylsl / LabRecorder, so no timestamp channel is included.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence
from urllib.error import URLError
from urllib.request import urlopen

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from pylsl import StreamInfo, StreamOutlet, local_clock


# ----------------------------
# User-tunable settings
# ----------------------------

STREAM_NAME = "FR3_State"
STREAM_TYPE = "RobotState"
STREAM_UID = "fr3_state_binary_v1"
PUBLISH_RATE_HZ = 50.0
STATE_API_URL = "http://127.0.0.1:8765/state"
STATE_API_TIMEOUT_SEC = 0.05

# PID file used by the launcher to track visual-servo lifecycle.
VISUAL_SERVO_PID_FILE = "/tmp/fr3_visual_servo.pid"

KT_PATTERNS = [
    r"run_gui\.sh",
    r"franka_kinesthetic_teaching_GUI",
]

# Thresholds for binary movement flags
ARM_VELOCITY_NORM_THRESHOLD = 0.01      # rad/s norm across non-gripper joints
GRIPPER_VELOCITY_THRESHOLD = 0.001      # joint velocity threshold
GRIPPER_POSITION_DELTA_THRESHOLD = 0.0005  # fallback if velocity missing
ARM_POSITION_DELTA_THRESHOLD = 0.0005   # fallback if velocity missing

# If your gripper joint names differ, update these.
GRIPPER_JOINT_NAME_HINTS = [
    "finger",
    "gripper",
    "leftfinger",
    "rightfinger",
    "panda_finger_joint",
    "fr3_finger_joint",
]

# Debounce settings to reduce flicker
REQUIRED_CONSECUTIVE_TRUE = 2
REQUIRED_CONSECUTIVE_FALSE = 2


# ----------------------------
# Helpers
# ----------------------------

def process_matches_any(patterns: Sequence[str]) -> bool:
    """
    Return True if any running process command line matches any regex pattern.
    Uses 'ps -eo pid,args' to inspect command lines.
    """
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,args"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return False

    lines = result.stdout.splitlines()
    for line in lines:
        for pattern in patterns:
            if re.search(pattern, line):
                return True
    return False


def pid_file_matches_process(pid_file: str, patterns: Sequence[str]) -> bool:
    pid: Optional[int] = None
    try:
        with open(pid_file, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError:
        return False

    if not content:
        return False

    try:
        pid = int(content)
    except ValueError:
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False

    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            cmdline = handle.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
    except OSError:
        return False

    for pattern in patterns:
        if re.search(pattern, cmdline):
            return True
    return False


def fetch_state_api_snapshot() -> Optional[Dict[str, int]]:
    """
    Return the current robot-state snapshot from the local API if available.
    Expected response shape:
        {"state": {"visual_servo_active": 0/1, ...}}
    """
    try:
        with urlopen(STATE_API_URL, timeout=STATE_API_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, OSError):
        return None

    state = payload.get("state")
    if not isinstance(state, dict):
        return None

    snapshot: Dict[str, int] = {}
    for key, value in state.items():
        if value is None:
            continue
        try:
            snapshot[key] = 1 if bool(int(value)) else 0
        except (TypeError, ValueError):
            continue
    return snapshot


def velocity_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values))


def looks_like_gripper_joint(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in GRIPPER_JOINT_NAME_HINTS)


@dataclass
class DebouncedFlag:
    state: int = 0
    true_count: int = 0
    false_count: int = 0

    def update(self, raw_value: bool) -> int:
        if raw_value:
            self.true_count += 1
            self.false_count = 0
            if self.true_count >= REQUIRED_CONSECUTIVE_TRUE:
                self.state = 1
        else:
            self.false_count += 1
            self.true_count = 0
            if self.false_count >= REQUIRED_CONSECUTIVE_FALSE:
                self.state = 0
        return self.state


# ----------------------------
# ROS / LSL publisher
# ----------------------------

class RobotStatePublisher(Node):
    def __init__(self) -> None:
        super().__init__("robot_state_publisher")

        self.subscription = self.create_subscription(
            JointState,
            "/joint_states",
            self.joint_state_callback,
            50,
        )

        # Last observed joint info
        self.last_joint_names: List[str] = []
        self.last_positions: Dict[str, float] = {}
        self.last_velocities: Dict[str, float] = {}
        self.last_joint_msg_time: Optional[float] = None
        self.prev_positions: Dict[str, float] = {}
        self.prev_joint_msg_time: Optional[float] = None

        # Debounced states
        self.visual_servo_flag = DebouncedFlag()
        self.kt_flag = DebouncedFlag()
        self.arm_moving_flag = DebouncedFlag()
        self.gripper_moving_flag = DebouncedFlag()

        # LSL setup
        info = StreamInfo(
            STREAM_NAME,
            STREAM_TYPE,
            4,                 # 4 binary channels
            PUBLISH_RATE_HZ,   # nominal sampling rate
            "int32",
            STREAM_UID,
        )

        channels = info.desc().append_child("channels")
        for label in [
            "visual_servo_active",
            "kt_active",
            "arm_moving",
            "gripper_moving",
        ]:
            ch = channels.append_child("channel")
            ch.append_child_value("label", label)
            ch.append_child_value("type", "binary")
            ch.append_child_value("unit", "0_or_1")

        self.outlet = StreamOutlet(info)

        self.timer = self.create_timer(1.0 / PUBLISH_RATE_HZ, self.publish_sample)

        self.get_logger().info("robot_state_publisher started.")
        self.get_logger().info(f"Publishing LSL stream: {STREAM_NAME}")

    def joint_state_callback(self, msg: JointState) -> None:
        now = time.monotonic()
        current_positions: Dict[str, float] = {}
        current_velocities: Dict[str, float] = {}

        for i, name in enumerate(msg.name):
            if i < len(msg.position):
                current_positions[name] = msg.position[i]
            if i < len(msg.velocity):
                current_velocities[name] = msg.velocity[i]

        self.prev_positions = self.last_positions.copy()
        self.prev_joint_msg_time = self.last_joint_msg_time
        self.last_joint_msg_time = now

        self.last_joint_names = list(msg.name)
        self.last_positions = current_positions
        self.last_velocities = current_velocities

    def compute_arm_moving_raw(self) -> bool:
        """
        Uses non-gripper joint velocities from /joint_states.
        Falls back to position deltas between successive joint-state messages.
        """
        if not self.last_joint_names:
            return False

        arm_vels: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            arm_vels.append(float(self.last_velocities.get(name, 0.0)))

        if not arm_vels:
            return False

        if velocity_norm(arm_vels) > ARM_VELOCITY_NORM_THRESHOLD:
            return True

        if not self.prev_positions or self.prev_joint_msg_time is None or self.last_joint_msg_time is None:
            return False

        dt = self.last_joint_msg_time - self.prev_joint_msg_time
        if dt <= 0:
            return False

        arm_position_rates: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            if name not in self.prev_positions or name not in self.last_positions:
                continue
            delta = float(self.last_positions[name]) - float(self.prev_positions[name])
            arm_position_rates.append(delta / dt)

        if not arm_position_rates:
            return False

        return velocity_norm(arm_position_rates) > ARM_POSITION_DELTA_THRESHOLD

    def compute_gripper_moving_raw(self) -> bool:
        """
        Prefers gripper joint velocity if available.
        Falls back to position deltas between successive joint-state messages.
        """
        if not self.last_joint_names:
            return False

        gripper_names = [n for n in self.last_joint_names if looks_like_gripper_joint(n)]
        if not gripper_names:
            return False

        # Velocity-based check
        for name in gripper_names:
            vel = abs(float(self.last_velocities.get(name, 0.0)))
            if vel > GRIPPER_VELOCITY_THRESHOLD:
                return True

        if not self.prev_positions:
            return False

        for name in gripper_names:
            if name not in self.prev_positions or name not in self.last_positions:
                continue
            if abs(float(self.last_positions[name]) - float(self.prev_positions[name])) > GRIPPER_POSITION_DELTA_THRESHOLD:
                return True

        return False

    def publish_sample(self) -> None:
        api_state = fetch_state_api_snapshot()

        visual_servo_raw = pid_file_matches_process(
            VISUAL_SERVO_PID_FILE,
            [r"run_visual_servo_combined\.sh", r"servoFrankaIBVS_(combined|CHRPS)"],
        )
        kt_raw = process_matches_any(KT_PATTERNS)
        arm_moving_raw = self.compute_arm_moving_raw()
        gripper_moving_raw = self.compute_gripper_moving_raw()

        if api_state is not None:
            visual_servo_raw = visual_servo_raw or bool(api_state.get("visual_servo_active", 0))
            kt_raw = kt_raw or bool(api_state.get("kt_active", 0))
            arm_moving_raw = arm_moving_raw or bool(api_state.get("arm_moving", 0))
            gripper_moving_raw = gripper_moving_raw or bool(api_state.get("gripper_moving", 0))

        visual_servo_active = self.visual_servo_flag.update(visual_servo_raw)
        kt_active = self.kt_flag.update(kt_raw)
        arm_moving = self.arm_moving_flag.update(arm_moving_raw)
        gripper_moving = self.gripper_moving_flag.update(gripper_moving_raw)

        sample = [
            int(visual_servo_active),
            int(kt_active),
            int(arm_moving),
            int(gripper_moving),
        ]

        self.outlet.push_sample(sample, local_clock())

    def shutdown(self) -> None:
        self.get_logger().info("Shutting down robot_state_publisher.")


def main() -> None:
    rclpy.init()
    node = RobotStatePublisher()

    def _handle_signal(signum, frame):
        node.get_logger().info(f"Received signal {signum}, shutting down.")
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        rclpy.spin(node)
    finally:
        if rclpy.ok():
            node.shutdown()
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
