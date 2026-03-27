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
- visual_servo_active: 1 if the tracked visual-servo PID file points to a live process
- kt_active: 1 if the tracked kinesthetic-teaching PID file points to a live process
- arm_moving: 1 if merged robot joint velocity norm is above threshold
- gripper_moving: 1 if merged gripper joint velocity/position change is above threshold

Notes:
- This version uses ROS 2 /joint_states for motion detection.
- You will likely need to adjust process patterns and gripper joint names.
- LSL timestamps are handled by pylsl / LabRecorder, so no timestamp channel is included.
"""

from __future__ import annotations

import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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

VISUAL_SERVO_PID_FILE = Path("/tmp/fr3_visual_servo.pid")
KT_PID_FILE = Path("/tmp/fr3_kinesthetic_gui.pid")

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
DIAGNOSTIC_LOG_PERIOD_SEC = 5.0
JOINT_STATE_TOPICS = [
    "/joint_states",
    "/franka/joint_states",
    "/franka_gripper/joint_states",
    "/fr3_gripper/joint_states",
]
TOPIC_STALE_AFTER_SEC = 1.0


# ----------------------------
# Helpers
# ----------------------------

def pid_file_process_is_alive(pid_file: Path) -> bool:
    """
    Return True if the PID file exists and points to a currently running process.
    Removes empty/stale PID files so the GUI and LSL publisher converge on the same state.
    """
    try:
        raw_pid = pid_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False
    except Exception:
        return False

    if not raw_pid:
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False

    try:
        pid = int(raw_pid)
    except ValueError:
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False


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

        self.subscriptions = [
            self.create_subscription(JointState, topic, self.joint_state_callback_for_topic(topic), 50)
            for topic in JOINT_STATE_TOPICS
        ]

        # Last observed joint info
        self.last_joint_names: List[str] = []
        self.last_positions: Dict[str, float] = {}
        self.last_velocities: Dict[str, float] = {}
        self.last_joint_msg_time: Optional[float] = None
        self.prev_positions: Dict[str, float] = {}
        self.prev_joint_msg_time: Optional[float] = None
        self.last_diagnostic_log_time: float = 0.0
        self.last_joint_state_topic: str = "none"
        self.topic_joint_states: Dict[str, Tuple[float, Dict[str, float], Dict[str, float]]] = {}

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
        self.get_logger().info(f"Listening for joint states on: {', '.join(JOINT_STATE_TOPICS)}")

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

    def joint_state_callback_for_topic(self, topic: str):
        def _callback(msg: JointState) -> None:
            now = time.monotonic()
            current_positions: Dict[str, float] = {}
            current_velocities: Dict[str, float] = {}

            for i, name in enumerate(msg.name):
                if i < len(msg.position):
                    current_positions[name] = msg.position[i]
                if i < len(msg.velocity):
                    current_velocities[name] = msg.velocity[i]

            self.topic_joint_states[topic] = (now, current_positions, current_velocities)
            self.last_joint_state_topic = topic
            self._refresh_joint_state_snapshot(now)

        return _callback

    def _refresh_joint_state_snapshot(self, now: float) -> None:
        merged_positions: Dict[str, float] = {}
        merged_velocities: Dict[str, float] = {}
        fresh_topics: List[Tuple[str, float]] = []

        for topic, (stamp, positions, velocities) in list(self.topic_joint_states.items()):
            age = now - stamp
            if age > TOPIC_STALE_AFTER_SEC:
                continue
            fresh_topics.append((topic, stamp))
            merged_positions.update(positions)
            merged_velocities.update(velocities)

        self.prev_positions = self.last_positions.copy()
        self.prev_joint_msg_time = self.last_joint_msg_time
        self.last_joint_msg_time = now
        self.last_positions = merged_positions
        self.last_velocities = merged_velocities
        self.last_joint_names = list(merged_positions.keys())

        if fresh_topics:
            freshest_topic = max(fresh_topics, key=lambda item: item[1])[0]
            self.last_joint_state_topic = freshest_topic

    def compute_arm_motion_metrics(self) -> Tuple[bool, float, float, int]:
        """
        Uses non-gripper joint velocities from /joint_states.
        Falls back to position deltas between successive joint-state messages.
        """
        if not self.last_joint_names:
            return False, 0.0, 0.0, 0

        arm_vels: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            arm_vels.append(float(self.last_velocities.get(name, 0.0)))

        if not arm_vels:
            return False, 0.0, 0.0, 0

        arm_velocity_norm = velocity_norm(arm_vels)
        if arm_velocity_norm > ARM_VELOCITY_NORM_THRESHOLD:
            return True, arm_velocity_norm, 0.0, len(arm_vels)

        if not self.prev_positions or self.prev_joint_msg_time is None or self.last_joint_msg_time is None:
            return False, arm_velocity_norm, 0.0, len(arm_vels)

        dt = self.last_joint_msg_time - self.prev_joint_msg_time
        if dt <= 0:
            return False, arm_velocity_norm, 0.0, len(arm_vels)

        arm_position_rates: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            if name not in self.prev_positions or name not in self.last_positions:
                continue
            delta = float(self.last_positions[name]) - float(self.prev_positions[name])
            arm_position_rates.append(delta / dt)

        if not arm_position_rates:
            return False, arm_velocity_norm, 0.0, len(arm_vels)

        arm_position_rate_norm = velocity_norm(arm_position_rates)
        return (
            arm_position_rate_norm > ARM_POSITION_DELTA_THRESHOLD,
            arm_velocity_norm,
            arm_position_rate_norm,
            len(arm_vels),
        )

    def compute_gripper_motion_metrics(self) -> Tuple[bool, List[str], float, float]:
        """
        Prefers gripper joint velocity if available.
        Falls back to position deltas between successive joint-state messages.
        """
        if not self.last_joint_names:
            return False, [], 0.0, 0.0

        gripper_names = [n for n in self.last_joint_names if looks_like_gripper_joint(n)]
        if not gripper_names:
            return False, [], 0.0, 0.0

        # Velocity-based check
        max_gripper_velocity = 0.0
        for name in gripper_names:
            vel = abs(float(self.last_velocities.get(name, 0.0)))
            max_gripper_velocity = max(max_gripper_velocity, vel)
            if vel > GRIPPER_VELOCITY_THRESHOLD:
                return True, gripper_names, max_gripper_velocity, 0.0

        if not self.prev_positions:
            return False, gripper_names, max_gripper_velocity, 0.0

        max_gripper_position_delta = 0.0
        for name in gripper_names:
            if name not in self.prev_positions or name not in self.last_positions:
                continue
            delta = abs(float(self.last_positions[name]) - float(self.prev_positions[name]))
            max_gripper_position_delta = max(max_gripper_position_delta, delta)
            if delta > GRIPPER_POSITION_DELTA_THRESHOLD:
                return True, gripper_names, max_gripper_velocity, max_gripper_position_delta

        return False, gripper_names, max_gripper_velocity, max_gripper_position_delta

    def maybe_log_diagnostics(
        self,
        sample: Sequence[int],
        arm_velocity_norm: float,
        arm_position_rate_norm: float,
        arm_joint_count: int,
        gripper_names: Sequence[str],
        gripper_velocity_max: float,
        gripper_position_delta_max: float,
    ) -> None:
        now = time.monotonic()
        if now - self.last_diagnostic_log_time < DIAGNOSTIC_LOG_PERIOD_SEC:
            return

        self.last_diagnostic_log_time = now

        if self.last_joint_msg_time is None:
            joint_state_age = "none"
        else:
            joint_state_age = f"{now - self.last_joint_msg_time:.3f}s"

        gripper_text = ",".join(gripper_names) if gripper_names else "none"
        self.get_logger().info(
            "LSL sample=%s joint_state_topic=%s joint_state_age=%s arm_joints=%d arm_vel_norm=%.6f "
            "arm_pos_rate_norm=%.6f gripper_joints=%s gripper_vel_max=%.6f "
            "gripper_pos_delta_max=%.6f"
            % (
                list(sample),
                self.last_joint_state_topic,
                joint_state_age,
                arm_joint_count,
                arm_velocity_norm,
                arm_position_rate_norm,
                gripper_text,
                gripper_velocity_max,
                gripper_position_delta_max,
            )
        )

        if self.last_joint_msg_time is None or (now - self.last_joint_msg_time) > 1.0:
            self.get_logger().warning(
                "No fresh /joint_states received recently. arm_moving and gripper_moving will stay 0."
            )
        if not gripper_names:
            self.get_logger().warning(
                "No gripper joints matched current hints. Update GRIPPER_JOINT_NAME_HINTS if needed."
            )

    def publish_sample(self) -> None:
        visual_servo_raw = pid_file_process_is_alive(VISUAL_SERVO_PID_FILE)
        kt_raw = pid_file_process_is_alive(KT_PID_FILE)
        arm_moving_raw, arm_velocity_norm, arm_position_rate_norm, arm_joint_count = self.compute_arm_motion_metrics()
        gripper_moving_raw, gripper_names, gripper_velocity_max, gripper_position_delta_max = self.compute_gripper_motion_metrics()

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
        self.maybe_log_diagnostics(
            sample,
            arm_velocity_norm,
            arm_position_rate_norm,
            arm_joint_count,
            gripper_names,
            gripper_velocity_max,
            gripper_position_delta_max,
        )

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
