#!/usr/bin/env python3
"""
robot_motion_monitor.py

Sidecar process that discovers ROS 2 JointState topics on the robot computer,
estimates arm/gripper motion, and pushes those flags into robot_state_api.py.
"""

from __future__ import annotations

import json
import math
import traceback
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


STATE_API_URL = "http://127.0.0.1:8765/state"
API_TIMEOUT_SEC = 0.1
API_TTL_SEC = 0.35
DISCOVERY_PERIOD_SEC = 1.0
PUBLISH_PERIOD_SEC = 0.1
TOPIC_STALE_AFTER_SEC = 1.0

ARM_VELOCITY_NORM_THRESHOLD = 0.01
GRIPPER_VELOCITY_THRESHOLD = 0.001
GRIPPER_POSITION_DELTA_THRESHOLD = 0.0005
ARM_POSITION_DELTA_THRESHOLD = 0.0005

GRIPPER_JOINT_NAME_HINTS = [
    "finger",
    "gripper",
    "leftfinger",
    "rightfinger",
    "panda_finger_joint",
    "fr3_finger_joint",
]


def velocity_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values))


def looks_like_gripper_joint(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in GRIPPER_JOINT_NAME_HINTS)


def post_state_update(payload: Dict[str, object]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        STATE_API_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=API_TIMEOUT_SEC):
            return
    except (URLError, OSError):
        return


class RobotMotionMonitor(Node):
    def __init__(self) -> None:
        super().__init__("robot_motion_monitor")

        self.joint_subscriptions: Dict[str, object] = {}
        self.topic_joint_states: Dict[str, Tuple[float, Dict[str, float], Dict[str, float]]] = {}
        self.last_positions: Dict[str, float] = {}
        self.prev_positions: Dict[str, float] = {}
        self.last_velocities: Dict[str, float] = {}
        self.last_joint_names: List[str] = []
        self.last_joint_msg_time: Optional[float] = None
        self.prev_joint_msg_time: Optional[float] = None
        self.last_arm_sent = False
        self.last_gripper_sent = False

        self.discovery_timer = self.create_timer(DISCOVERY_PERIOD_SEC, self.discover_joint_state_topics)
        self.publish_timer = self.create_timer(PUBLISH_PERIOD_SEC, self.publish_motion_state)

        self.get_logger().info("robot_motion_monitor started.")
        self.discover_joint_state_topics()

    def discover_joint_state_topics(self) -> None:
        topic_names_and_types = self.get_topic_names_and_types()
        for topic_name, topic_types in topic_names_and_types:
            if "sensor_msgs/msg/JointState" not in topic_types:
                continue
            if topic_name in self.joint_subscriptions:
                continue
            if "joint" not in topic_name.lower() and "gripper" not in topic_name.lower():
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
            positions: Dict[str, float] = {}
            velocities: Dict[str, float] = {}

            for i, joint_name in enumerate(msg.name):
                if i < len(msg.position):
                    positions[joint_name] = float(msg.position[i])
                if i < len(msg.velocity):
                    velocities[joint_name] = float(msg.velocity[i])

            self.topic_joint_states[topic_name] = (now, positions, velocities)
            self.refresh_joint_state_snapshot(now)

        return _callback

    def refresh_joint_state_snapshot(self, now: float) -> None:
        merged_positions: Dict[str, float] = {}
        merged_velocities: Dict[str, float] = {}

        for stamp, positions, velocities in self.topic_joint_states.values():
            if now - stamp > TOPIC_STALE_AFTER_SEC:
                continue
            merged_positions.update(positions)
            merged_velocities.update(velocities)

        self.prev_positions = self.last_positions.copy()
        self.prev_joint_msg_time = self.last_joint_msg_time
        self.last_joint_msg_time = now
        self.last_positions = merged_positions
        self.last_velocities = merged_velocities
        self.last_joint_names = list(merged_positions.keys())

    def compute_arm_moving(self) -> bool:
        if not self.last_joint_names or self.last_joint_msg_time is None:
            return False
        if time.monotonic() - self.last_joint_msg_time > TOPIC_STALE_AFTER_SEC:
            return False

        arm_vels: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            arm_vels.append(float(self.last_velocities.get(name, 0.0)))

        if arm_vels and velocity_norm(arm_vels) > ARM_VELOCITY_NORM_THRESHOLD:
            return True

        if not self.prev_positions or self.prev_joint_msg_time is None:
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
            arm_position_rates.append((self.last_positions[name] - self.prev_positions[name]) / dt)

        return bool(arm_position_rates) and velocity_norm(arm_position_rates) > ARM_POSITION_DELTA_THRESHOLD

    def compute_gripper_moving(self) -> bool:
        if not self.last_joint_names or self.last_joint_msg_time is None:
            return False
        if time.monotonic() - self.last_joint_msg_time > TOPIC_STALE_AFTER_SEC:
            return False

        gripper_names = [name for name in self.last_joint_names if looks_like_gripper_joint(name)]
        if not gripper_names:
            return False

        for name in gripper_names:
            if abs(float(self.last_velocities.get(name, 0.0))) > GRIPPER_VELOCITY_THRESHOLD:
                return True

        if not self.prev_positions:
            return False

        for name in gripper_names:
            if name not in self.prev_positions or name not in self.last_positions:
                continue
            if abs(self.last_positions[name] - self.prev_positions[name]) > GRIPPER_POSITION_DELTA_THRESHOLD:
                return True

        return False

    def publish_motion_state(self) -> None:
        arm_moving = self.compute_arm_moving()
        gripper_moving = self.compute_gripper_moving()

        payload: Dict[str, object] = {"ttl_sec": API_TTL_SEC}
        if arm_moving:
            payload["arm_moving"] = 1
        if gripper_moving:
            payload["gripper_moving"] = 1

        if len(payload) > 1:
            post_state_update(payload)
            self.last_arm_sent = arm_moving
            self.last_gripper_sent = gripper_moving
        else:
            self.last_arm_sent = False
            self.last_gripper_sent = False


def main() -> None:
    node: Optional[RobotMotionMonitor] = None
    try:
        rclpy.init()
        node = RobotMotionMonitor()
        rclpy.spin(node)
    except Exception:
        traceback.print_exc()
        raise
    finally:
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
