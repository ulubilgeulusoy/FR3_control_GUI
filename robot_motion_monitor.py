#!/usr/bin/env python3
"""
robot_motion_monitor.py

Sidecar process that discovers ROS 2 JointState topics on the robot computer,
estimates arm/gripper motion, and pushes those flags into robot_state_api.py.
"""

from __future__ import annotations

import json
import importlib
import math
import os
import traceback
import time
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

import rclpy
from action_msgs.msg import GoalStatusArray
from rclpy.node import Node
from sensor_msgs.msg import JointState


STATE_API_URL = "http://127.0.0.1:8765/state"
API_TIMEOUT_SEC = 0.1
API_TTL_SEC = 0.35
DISCOVERY_PERIOD_SEC = 1.0
PUBLISH_PERIOD_SEC = 0.1
TOPIC_STALE_AFTER_SEC = 1.0
DIAGNOSTIC_PERIOD_SEC = 2.0
ACTION_STATUS_STALE_AFTER_SEC = 1.0
VISUAL_SERVO_PID_FILE = os.environ.get("FR3_VISUAL_SERVO_PID_FILE", "/tmp/fr3_visual_servo.pid")
VISUAL_SERVO_CPU_STALE_AFTER_SEC = 0.6
VISUAL_SERVO_PROCESS_HINTS = (
    "servofrankaibvs",
    "run_visual_servo_combined",
)
FR3_ROBOT_IP = os.environ.get("FR3_ROBOT_IP", "172.16.0.2")
ENABLE_FRANKY_BACKEND = os.environ.get("FR3_ENABLE_FRANKY_BACKEND", "1").strip() not in ("0", "false", "False")
ENABLE_VISUAL_SERVO_CPU_FALLBACK = os.environ.get("FR3_ENABLE_VISUAL_SERVO_CPU_FALLBACK", "0").strip() in ("1", "true", "True")
DIRECT_BACKEND_RETRY_SEC = 5.0

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


def read_pid_file(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError:
        return None

    if not content:
        return None

    try:
        return int(content)
    except ValueError:
        return None


def list_proc_pids() -> List[int]:
    pids: List[int] = []
    try:
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                pids.append(int(entry))
    except OSError:
        return []
    return pids


def read_proc_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return ""

    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def read_proc_ppid(pid: int) -> Optional[int]:
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("PPid:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        return None

    return None


def read_proc_cpu_ticks(pid: int) -> Optional[int]:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError:
        return None

    end_comm = raw.rfind(")")
    if end_comm < 0:
        return None

    fields = raw[end_comm + 2 :].split()
    if len(fields) < 15:
        return None

    try:
        utime = int(fields[11])
        stime = int(fields[12])
    except ValueError:
        return None

    return utime + stime


class RobotMotionMonitor(Node):
    def __init__(self) -> None:
        super().__init__("robot_motion_monitor")

        self.joint_subscriptions: Dict[str, object] = {}
        self.gripper_status_subscriptions: Dict[str, object] = {}
        self.topic_joint_states: Dict[str, Tuple[float, Dict[str, float], Dict[str, float]]] = {}
        self.last_gripper_action_time: Optional[float] = None
        self.last_gripper_action_active = False
        self.last_positions: Dict[str, float] = {}
        self.prev_positions: Dict[str, float] = {}
        self.last_velocities: Dict[str, float] = {}
        self.last_joint_names: List[str] = []
        self.last_joint_msg_time: Optional[float] = None
        self.prev_joint_msg_time: Optional[float] = None
        self.last_arm_sent = False
        self.last_gripper_sent = False
        self.last_diagnostic_time = 0.0
        self.last_visual_servo_cpu_sample: Dict[int, Tuple[float, int]] = {}
        self.last_visual_servo_active_time: Optional[float] = None
        self.last_visual_servo_process_active = False
        self.last_visual_servo_pids: List[int] = []
        self.direct_backend_name = "none"
        self.direct_backend_error: Optional[str] = None
        self.direct_backend_robot = None
        self.direct_backend_last_attempt_time = 0.0
        self.direct_backend_last_sample_time: Optional[float] = None
        self.direct_backend_positions: Dict[str, float] = {}
        self.direct_backend_prev_positions: Dict[str, float] = {}
        self.direct_backend_velocities: Dict[str, float] = {}
        self.direct_backend_last_arm_moving = False

        self.discovery_timer = self.create_timer(DISCOVERY_PERIOD_SEC, self.discover_joint_state_topics)
        self.publish_timer = self.create_timer(PUBLISH_PERIOD_SEC, self.publish_motion_state)

        self.get_logger().info("robot_motion_monitor started.")
        self.discover_joint_state_topics()

    def discover_joint_state_topics(self) -> None:
        topic_names_and_types = self.get_topic_names_and_types()
        for topic_name, topic_types in topic_names_and_types:
            if "sensor_msgs/msg/JointState" not in topic_types:
                if "action_msgs/msg/GoalStatusArray" in topic_types:
                    self._maybe_subscribe_gripper_status(topic_name)
                continue

            self._maybe_subscribe_joint_state(topic_name)

    def _maybe_subscribe_joint_state(self, topic_name: str) -> None:
        if topic_name in self.joint_subscriptions:
            return
        if "joint" not in topic_name.lower() and "gripper" not in topic_name.lower():
            return

        self.joint_subscriptions[topic_name] = self.create_subscription(
            JointState,
            topic_name,
            self._make_joint_state_callback(topic_name),
            50,
        )
        self.get_logger().info(f"Subscribed to JointState topic: {topic_name}")

    def _maybe_subscribe_gripper_status(self, topic_name: str) -> None:
        lowered = topic_name.lower()
        if topic_name in self.gripper_status_subscriptions:
            return
        if "gripper" not in lowered:
            return
        if "status" not in lowered and "_action" not in lowered:
            return

        self.gripper_status_subscriptions[topic_name] = self.create_subscription(
            GoalStatusArray,
            topic_name,
            self._make_gripper_status_callback(topic_name),
            20,
        )
        self.get_logger().info(f"Subscribed to gripper action status topic: {topic_name}")

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

    def _make_gripper_status_callback(self, topic_name: str):
        def _callback(msg: GoalStatusArray) -> None:
            now = time.monotonic()
            active = any(status.status in (1, 2, 3) for status in msg.status_list)
            self.last_gripper_action_time = now
            self.last_gripper_action_active = active
            if active:
                self.get_logger().info(f"Active gripper action detected on: {topic_name}")

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

    def discover_visual_servo_processes(self) -> List[int]:
        root_pid = read_pid_file(VISUAL_SERVO_PID_FILE)
        if root_pid is None:
            return []

        all_pids = list_proc_pids()
        if root_pid not in all_pids:
            return []

        children_by_parent: Dict[int, List[int]] = {}
        for pid in all_pids:
            ppid = read_proc_ppid(pid)
            if ppid is None:
                continue
            children_by_parent.setdefault(ppid, []).append(pid)

        stack = [root_pid]
        descendants: List[int] = []
        seen = set()
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            descendants.append(pid)
            stack.extend(children_by_parent.get(pid, []))

        matches: List[int] = []
        for pid in descendants:
            cmdline = read_proc_cmdline(pid).lower()
            if any(hint in cmdline for hint in VISUAL_SERVO_PROCESS_HINTS):
                matches.append(pid)

        return sorted(set(matches or descendants))

    def compute_visual_servo_process_motion(self) -> bool:
        now = time.monotonic()
        pids = self.discover_visual_servo_processes()
        self.last_visual_servo_pids = pids

        next_samples: Dict[int, Tuple[float, int]] = {}
        saw_progress = False
        for pid in pids:
            ticks = read_proc_cpu_ticks(pid)
            if ticks is None:
                continue

            previous = self.last_visual_servo_cpu_sample.get(pid)
            next_samples[pid] = (now, ticks)
            if previous is None:
                continue

            _, previous_ticks = previous
            if ticks > previous_ticks:
                saw_progress = True

        self.last_visual_servo_cpu_sample = next_samples
        if saw_progress:
            self.last_visual_servo_active_time = now

        active = (
            self.last_visual_servo_active_time is not None
            and (now - self.last_visual_servo_active_time) <= VISUAL_SERVO_CPU_STALE_AFTER_SEC
        )
        self.last_visual_servo_process_active = active
        return active

    def ensure_direct_backend(self) -> bool:
        if not ENABLE_FRANKY_BACKEND:
            self.direct_backend_name = "disabled"
            return False
        if self.direct_backend_robot is not None:
            return True

        now = time.monotonic()
        if (now - self.direct_backend_last_attempt_time) < DIRECT_BACKEND_RETRY_SEC:
            return False
        self.direct_backend_last_attempt_time = now

        try:
            franky = importlib.import_module("franky")
            robot_class = getattr(franky, "Robot", None)
            if robot_class is None:
                raise RuntimeError("franky.Robot not found")
            self.direct_backend_robot = robot_class(FR3_ROBOT_IP)
            self.direct_backend_name = "franky"
            self.direct_backend_error = None
            self.get_logger().info(f"Direct backend connected via franky to {FR3_ROBOT_IP}")
            return True
        except Exception as exc:
            self.direct_backend_robot = None
            self.direct_backend_name = "unavailable"
            self.direct_backend_error = str(exc)
            return False

    def compute_direct_backend_arm_moving(self) -> bool:
        active_visual_servo_pids = self.discover_visual_servo_processes()
        self.last_visual_servo_pids = active_visual_servo_pids
        self.last_visual_servo_process_active = bool(active_visual_servo_pids)
        if not active_visual_servo_pids:
            self.direct_backend_last_arm_moving = False
            return False

        if not self.ensure_direct_backend():
            self.direct_backend_last_arm_moving = False
            return False

        now = time.monotonic()
        robot = self.direct_backend_robot

        try:
            joint_state = getattr(robot, "current_joint_state", None)
            if joint_state is None:
                current_joint_state = getattr(robot, "currentJointState", None)
                if callable(current_joint_state):
                    joint_state = current_joint_state()
            if joint_state is None:
                raise RuntimeError("no joint state accessor available from direct backend")

            positions_raw = (
                getattr(joint_state, "position", None)
                or getattr(joint_state, "positions", None)
            )
            velocities_raw = (
                getattr(joint_state, "velocity", None)
                or getattr(joint_state, "velocities", None)
            )

            if positions_raw is None:
                current_joint_positions = getattr(robot, "currentJointPositions", None)
                if callable(current_joint_positions):
                    positions_raw = current_joint_positions()
            if velocities_raw is None:
                current_joint_velocities = getattr(robot, "currentJointVelocities", None)
                if callable(current_joint_velocities):
                    velocities_raw = current_joint_velocities()

            if positions_raw is None or velocities_raw is None:
                raise RuntimeError("direct backend did not expose joint positions/velocities")

            positions = list(positions_raw)
            velocities = list(velocities_raw)
            if len(positions) < 7:
                raise RuntimeError("joint_state.position did not contain 7 joints")

            names = [f"fr3_joint{i}" for i in range(1, len(positions) + 1)]
            latest_positions = {name: float(value) for name, value in zip(names, positions)}
            latest_velocities = {name: float(value) for name, value in zip(names, velocities)}

            moving = False
            if latest_velocities and velocity_norm(list(latest_velocities.values())) > ARM_VELOCITY_NORM_THRESHOLD:
                moving = True
            elif self.direct_backend_positions and self.direct_backend_last_sample_time is not None:
                dt = now - self.direct_backend_last_sample_time
                if dt > 0:
                    rates = [
                        (latest_positions[name] - self.direct_backend_positions[name]) / dt
                        for name in latest_positions
                        if name in self.direct_backend_positions
                    ]
                    moving = bool(rates) and velocity_norm(rates) > ARM_POSITION_DELTA_THRESHOLD

            self.direct_backend_prev_positions = self.direct_backend_positions
            self.direct_backend_positions = latest_positions
            self.direct_backend_velocities = latest_velocities
            self.direct_backend_last_sample_time = now
            self.direct_backend_error = None
            self.direct_backend_last_arm_moving = moving
            return moving
        except Exception as exc:
            self.direct_backend_error = str(exc)
            self.direct_backend_last_arm_moving = False
            return False

    def compute_visual_servo_fallback_arm_moving(self) -> bool:
        if self.compute_direct_backend_arm_moving():
            return True
        if ENABLE_VISUAL_SERVO_CPU_FALLBACK:
            return self.compute_visual_servo_process_motion()
        self.compute_visual_servo_process_motion()
        return False

    def compute_arm_moving(self) -> bool:
        if not self.last_joint_names or self.last_joint_msg_time is None:
            return self.compute_visual_servo_fallback_arm_moving()
        if time.monotonic() - self.last_joint_msg_time > TOPIC_STALE_AFTER_SEC:
            return self.compute_visual_servo_fallback_arm_moving()

        arm_vels: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            arm_vels.append(float(self.last_velocities.get(name, 0.0)))

        if arm_vels and velocity_norm(arm_vels) > ARM_VELOCITY_NORM_THRESHOLD:
            return True

        if not self.prev_positions or self.prev_joint_msg_time is None:
            return self.compute_visual_servo_fallback_arm_moving()

        dt = self.last_joint_msg_time - self.prev_joint_msg_time
        if dt <= 0:
            return self.compute_visual_servo_fallback_arm_moving()

        arm_position_rates: List[float] = []
        for name in self.last_joint_names:
            if looks_like_gripper_joint(name):
                continue
            if name not in self.prev_positions or name not in self.last_positions:
                continue
            arm_position_rates.append((self.last_positions[name] - self.prev_positions[name]) / dt)

        if bool(arm_position_rates) and velocity_norm(arm_position_rates) > ARM_POSITION_DELTA_THRESHOLD:
            return True

        return self.compute_visual_servo_fallback_arm_moving()

    def compute_gripper_moving(self) -> bool:
        now = time.monotonic()
        if (
            self.last_gripper_action_time is not None
            and self.last_gripper_action_active
            and (now - self.last_gripper_action_time) <= ACTION_STATUS_STALE_AFTER_SEC
        ):
            return True

        if not self.last_joint_names or self.last_joint_msg_time is None:
            return False
        if now - self.last_joint_msg_time > TOPIC_STALE_AFTER_SEC:
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

        self.maybe_log_diagnostics(arm_moving, gripper_moving)

    def maybe_log_diagnostics(self, arm_moving: bool, gripper_moving: bool) -> None:
        now = time.monotonic()
        if now - self.last_diagnostic_time < DIAGNOSTIC_PERIOD_SEC:
            return

        self.last_diagnostic_time = now

        joint_age = "none" if self.last_joint_msg_time is None else f"{now - self.last_joint_msg_time:.3f}s"
        gripper_names = [name for name in self.last_joint_names if looks_like_gripper_joint(name)]
        arm_names = [name for name in self.last_joint_names if not looks_like_gripper_joint(name)]

        self.get_logger().info(
            "topics=%s gripper_status_topics=%s visual_servo_pids=%s direct_backend=%s direct_backend_arm_moving=%d direct_backend_error=%s joint_count=%d arm_joints=%s gripper_joints=%s joint_age=%s arm_moving=%d gripper_moving=%d gripper_action_active=%d visual_servo_process_active=%d"
            % (
                ",".join(sorted(self.joint_subscriptions.keys())) or "none",
                ",".join(sorted(self.gripper_status_subscriptions.keys())) or "none",
                ",".join(str(pid) for pid in self.last_visual_servo_pids) or "none",
                self.direct_backend_name,
                int(self.direct_backend_last_arm_moving),
                (self.direct_backend_error or "none")[:120],
                len(self.last_joint_names),
                ",".join(arm_names[:8]) or "none",
                ",".join(gripper_names[:8]) or "none",
                joint_age,
                int(arm_moving),
                int(gripper_moving),
                int(self.last_gripper_action_active),
                int(self.last_visual_servo_process_active),
            )
        )


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
