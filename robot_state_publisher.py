#!/usr/bin/env python3
"""
robot_state_publisher.py

Publishes a simple binary robot-state LSL stream from the Ubuntu robot computer.

Channels:
    0: visual_servo_active
    1: kt_active
    2: teaching_active
    3: running_active
    4: arm_moving
    5: gripper_moving

Current logic:
- visual_servo_active: 1 if a matching visual-servo process is running
- kt_active: 1 if a matching kinesthetic-teaching process is running
- teaching_active: 1 if a matching teaching/teach-mode process is running
- running_active: 1 if a matching trajectory-run/playback process is running
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
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
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

# Process-name patterns used to decide whether the tools are active.
# Adjust these if your actual process names differ.
VISUAL_SERVO_PATTERNS = [
    r"run_visual_servo_combined\.sh",
    r"FR3_visual_servo_examples",
    r"visual_servo",
    r"servoFrankaIBVS_combined",
]

KT_PATTERNS = [
    r"run_gui\.sh",
    r"franka_kinesthetic_teaching_GUI",
    r"franka_teach",
    r"kinesthetic",
]

TEACHING_PATTERNS = [
    r"franka_teach",
    r"teach",
    r"teaching",
    r"gravity",
]

RUNNING_PATTERNS = [
    r"trajectory",
    r"playback",
    r"execute",
    r"running",
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

        self.joint_subscriptions: Dict[str, object] = {}
        self.topic_joint_states: Dict[str, Tuple[float, Dict[str, float], Dict[str, float]]] = {}
        self.discovery_timer = self.create_timer(1.0, self.discover_joint_state_topics)

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
        self.teaching_flag = DebouncedFlag()
        self.running_flag = DebouncedFlag()
        self.arm_moving_flag = DebouncedFlag()
        self.gripper_moving_flag = DebouncedFlag()

        # LSL setup
        info = StreamInfo(
            STREAM_NAME,
            STREAM_TYPE,
            6,                 # 6 binary channels
            PUBLISH_RATE_HZ,   # nominal sampling rate
            "int32",
            STREAM_UID,
        )

        channels = info.desc().append_child("channels")
        for label in [
            "visual_servo_active",
            "kt_active",
            "teaching_active",
            "running_active",
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
        self.discover_joint_state_topics()

    def discover_joint_state_topics(self) -> None:
        topic_names_and_types = self.get_topic_names_and_types()
        for topic_name, topic_types in topic_names_and_types:
            if "sensor_msgs/msg/JointState" not in topic_types:
                continue
            if topic_name in self.joint_subscriptions:
                continue
            self.joint_subscriptions[topic_name] = self.create_subscription(
                JointState,
                topic_name,
                self._make_joint_state_callback(topic_name),
                50,
            )
            self.get_logger().info(f"Subscribed to JointState topic: {topic_name}")

    def _make_joint_state_callback(self, topic_name: str):
        def _callback(msg: JointState) -> None:
            now = time.monotonic()
            current_positions: Dict[str, float] = {}
            current_velocities: Dict[str, float] = {}

            for i, name in enumerate(msg.name):
                if i < len(msg.position):
                    current_positions[name] = msg.position[i]
                if i < len(msg.velocity):
                    current_velocities[name] = msg.velocity[i]

            self.topic_joint_states[topic_name] = (now, current_positions, current_velocities)
            self.refresh_joint_state_snapshot(now)

        return _callback

    def refresh_joint_state_snapshot(self, now: float) -> None:
        current_positions: Dict[str, float] = {}
        current_velocities: Dict[str, float] = {}

        for stamp, positions, velocities in self.topic_joint_states.values():
            if now - stamp > 1.0:
                continue
            current_positions.update(positions)
            current_velocities.update(velocities)

        self.prev_positions = self.last_positions.copy()
        self.prev_joint_msg_time = self.last_joint_msg_time
        self.last_joint_msg_time = now

        self.last_joint_names = list(current_positions.keys())
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

        visual_servo_raw = process_matches_any(VISUAL_SERVO_PATTERNS)
        kt_raw = process_matches_any(KT_PATTERNS)
        teaching_raw = process_matches_any(TEACHING_PATTERNS)
        running_raw = process_matches_any(RUNNING_PATTERNS)
        arm_moving_raw = self.compute_arm_moving_raw()
        gripper_moving_raw = self.compute_gripper_moving_raw()

        if api_state is not None:
            visual_servo_raw = visual_servo_raw or bool(api_state.get("visual_servo_active", 0))
            kt_raw = kt_raw or bool(api_state.get("kt_active", 0))
            teaching_raw = teaching_raw or bool(api_state.get("teaching_active", 0))
            running_raw = running_raw or bool(api_state.get("running_active", 0))
            arm_moving_raw = arm_moving_raw or bool(api_state.get("arm_moving", 0))
            gripper_moving_raw = gripper_moving_raw or bool(api_state.get("gripper_moving", 0))

        visual_servo_active = self.visual_servo_flag.update(visual_servo_raw)
        kt_active = self.kt_flag.update(kt_raw)
        teaching_active = self.teaching_flag.update(teaching_raw)
        running_active = self.running_flag.update(running_raw)
        arm_moving = self.arm_moving_flag.update(arm_moving_raw)
        gripper_moving = self.gripper_moving_flag.update(gripper_moving_raw)

        sample = [
            int(visual_servo_active),
            int(kt_active),
            int(teaching_active),
            int(running_active),
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
