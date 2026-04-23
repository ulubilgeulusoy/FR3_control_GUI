import os
import json
import shlex
import signal
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from urllib.request import Request, urlopen

try:
    from pylsl import resolve_byprop
except Exception:
    resolve_byprop = None


class FR3LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FR3 Local Launcher")
        self.root.geometry("960x720")
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        self.visual_dir = tk.StringVar(value="/home/parc/FR3_visual_servo_examples")
        self.kinesthetic_dir = tk.StringVar(value="/home/parc/franka_kinesthetic_teaching_GUI")
        self.robot_ip = tk.StringVar(value="172.16.0.2")
        self.emc_path = tk.StringVar(value="config/eMc.yaml")
        self.visual_mode = tk.StringVar(value="1")

        self.status_text = tk.StringVar(value="Local mode")
        self.lsl_status_text = tk.StringVar(value="LSL: checking...")
        self.lsl_status_color = "#b00020"

        self.visual_pid_file = "/tmp/fr3_visual_servo.pid"
        self.kinesthetic_pid_file = "/tmp/fr3_kinesthetic_gui.pid"
        self.state_api_pid_file = "/tmp/fr3_state_api.pid"
        self.motion_monitor_pid_file = "/tmp/fr3_motion_monitor.pid"
        self.lsl_publisher_pid_file = "/tmp/fr3_lsl_publisher.pid"
        self.visual_log_file = "/tmp/fr3_visual_servo.log"
        self.kinesthetic_log_file = "/tmp/fr3_kinesthetic.log"
        self.state_api_log_file = "/tmp/fr3_state_api.log"
        self.motion_monitor_log_file = "/tmp/fr3_motion_monitor.log"
        self.lsl_publisher_log_file = "/tmp/fr3_lsl_publisher.log"

        self.visual_proc = None
        self.kinesthetic_proc = None
        self.state_api_proc = None
        self.motion_monitor_proc = None
        self.lsl_publisher_proc = None

        self._build_ui()
        self.cleanup_managed_processes()
        self.lsl_status_text.set("LSL: inactive")
        self.root.after(500, self.refresh_lsl_status)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="FR3 Local Control Interface", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.status_text).pack(side="right")

        cfg = ttk.LabelFrame(frame, text="Local Paths and Launch Args", padding=10)
        cfg.pack(fill="x", pady=(0, 10))

        ttk.Label(cfg, text="Visual Servo Repo").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(cfg, textvariable=self.visual_dir).grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(cfg, text="Kinesthetic Repo").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(cfg, textvariable=self.kinesthetic_dir).grid(row=1, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(cfg, text="Robot IP").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(cfg, textvariable=self.robot_ip).grid(row=2, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(cfg, text="eMc Path").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(cfg, textvariable=self.emc_path).grid(row=3, column=1, sticky="ew", padx=8, pady=4)

        ttk.Label(cfg, text="Visual Mode").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(cfg, textvariable=self.visual_mode, values=["1", "2"], state="readonly", width=8).grid(
            row=4,
            column=1,
            sticky="w",
            padx=8,
            pady=4,
        )

        cfg.columnconfigure(1, weight=1)

        button_area = ttk.Frame(frame)
        button_area.pack(fill="x", pady=(0, 10))

        visual_box = ttk.LabelFrame(button_area, text="Visual Servoing", padding=10)
        visual_box.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ttk.Button(visual_box, text="Start Visual Servo", command=self.start_visual_servo).pack(fill="x", pady=4)
        ttk.Button(visual_box, text="Stop Visual Servo", command=self.stop_visual_servo).pack(fill="x", pady=4)
        ttk.Button(visual_box, text="Kill Visual Servo", command=self.kill_visual_servo).pack(fill="x", pady=4)

        kin_box = ttk.LabelFrame(button_area, text="Kinesthetic Teaching", padding=10)
        kin_box.pack(side="left", fill="both", expand=True, padx=(5, 0))
        ttk.Button(kin_box, text="Start Kinesthetic GUI", command=self.start_kinesthetic).pack(fill="x", pady=4)
        ttk.Button(kin_box, text="Stop Kinesthetic GUI", command=self.stop_kinesthetic).pack(fill="x", pady=4)
        ttk.Button(kin_box, text="Kill Kinesthetic GUI", command=self.kill_kinesthetic).pack(fill="x", pady=4)

        state_box = ttk.LabelFrame(frame, text="Robot State / LSL", padding=10)
        state_box.pack(fill="x", pady=(0, 10))
        self.start_lsl_button = ttk.Button(state_box, text="Start LSL Stream", command=self.start_lsl_stream)
        self.start_lsl_button.pack(side="left")
        self.stop_lsl_button = ttk.Button(state_box, text="Stop LSL Stream", command=self.stop_lsl_stream)
        self.stop_lsl_button.pack(side="left", padx=8)
        self.lsl_status_label = tk.Label(
            state_box,
            textvariable=self.lsl_status_text,
            fg=self.lsl_status_color,
            font=("Segoe UI", 10, "bold"),
        )
        self.lsl_status_label.pack(side="right")

        tools = ttk.Frame(frame)
        tools.pack(fill="x", pady=(0, 10))
        ttk.Button(tools, text="Check Local Status", command=self.check_local_status).pack(side="left")
        ttk.Button(tools, text="Show Last Logs", command=self.show_last_logs).pack(side="left", padx=8)

        info = ttk.Label(
            frame,
            text="This branch runs everything locally on the same machine as the robot stack.",
        )
        info.pack(anchor="w", pady=(0, 8))

        log_box = ttk.LabelFrame(frame, text="Log", padding=10)
        log_box.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(log_box, wrap="word", height=25)
        self.log_text.pack(fill="both", expand=True)

    def append_log(self, text):
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def _run_bash_async(self, command, label):
        def worker():
            try:
                proc = subprocess.run(["bash", "-lc", command], capture_output=True, text=True)
                msg = f"[{label}] exit={proc.returncode}\n"
                if proc.stdout:
                    msg += proc.stdout
                    if not proc.stdout.endswith("\n"):
                        msg += "\n"
                if proc.stderr:
                    msg += proc.stderr
                    if not proc.stderr.endswith("\n"):
                        msg += "\n"
                if not proc.stdout and not proc.stderr:
                    msg += "(no output)\n"
                self.root.after(0, lambda: self.append_log(msg))
            except Exception as exc:
                self.root.after(0, lambda: self.append_log(f"[{label}] error: {exc}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def _post_state_update_async(self, label, payload):
        def worker():
            try:
                body = json.dumps(payload).encode("utf-8")
                request = Request(
                    "http://127.0.0.1:8765/state",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=0.2):
                    pass
            except Exception as exc:
                self.root.after(0, lambda: self.append_log(f"[{label}] state API update failed: {exc}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def _launch_local_gui_async(self, label, remote_inner_command, proc_attr):
        def worker():
            try:
                current = getattr(self, proc_attr)
                if current is not None and current.poll() is None:
                    self.root.after(0, lambda: self.append_log(f"[{label}] already running.\n"))
                    return

                bash_cmd = f"source /opt/ros/humble/setup.bash && {remote_inner_command}"
                proc = subprocess.Popen(
                    ["bash", "-lc", bash_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                setattr(self, proc_attr, proc)
                self.root.after(0, lambda: self.append_log(f"[{label}] launched locally.\n"))
                if label == "Start Visual Servo":
                    self._post_state_update_async("Visual Servo", {"visual_servo_active": 1})
                elif label == "Start Kinesthetic":
                    self._post_state_update_async("Kinesthetic", {"kt_active": 1})

                if proc.stdout is not None:
                    for line in proc.stdout:
                        self.root.after(0, lambda ln=line: self.append_log(f"[{label}] {ln}"))

                code = proc.wait()
                self.root.after(0, lambda: self.append_log(f"[{label}] exited with code {code}\n"))
                if label == "Start Visual Servo":
                    self._post_state_update_async("Visual Servo", {"visual_servo_active": 0})
                elif label == "Start Kinesthetic":
                    self._post_state_update_async("Kinesthetic", {"kt_active": 0})
            except Exception as exc:
                self.root.after(0, lambda: self.append_log(f"[{label}] launch error: {exc}\n"))
            finally:
                setattr(self, proc_attr, None)

        threading.Thread(target=worker, daemon=True).start()

    def _start_managed_service(self, label, pid_file, log_file, proc_attr, command):
        def worker():
            try:
                current = getattr(self, proc_attr)
                if current is not None and current.poll() is None:
                    self.root.after(0, lambda: self.append_log(f"[{label}] already running.\n"))
                    return

                if os.path.isfile(pid_file):
                    try:
                        with open(pid_file, "r", encoding="utf-8") as fp:
                            raw = fp.read().strip()
                        if raw:
                            os.kill(int(raw), 0)
                            self.root.after(0, lambda: self.append_log(f"[{label}] already running from PID file.\n"))
                            return
                    except Exception:
                        try:
                            os.remove(pid_file)
                        except OSError:
                            pass

                shell_command = (
                    "source /opt/ros/humble/setup.bash && "
                    f"cd {shlex.quote(self.base_dir)} && "
                    f"echo $$ > {shlex.quote(pid_file)} && "
                    f"exec {command}"
                )
                log_handle = open(log_file, "a", encoding="utf-8")
                proc = subprocess.Popen(
                    ["bash", "-lc", shell_command],
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                setattr(self, proc_attr, proc)
                self.root.after(0, lambda: self.append_log(f"[{label}] launched.\n"))
                code = proc.wait()
                self.root.after(0, lambda: self.append_log(f"[{label}] exited with code {code}\n"))
            except Exception as exc:
                self.root.after(0, lambda: self.append_log(f"[{label}] launch error: {exc}\n"))
            finally:
                setattr(self, proc_attr, None)
                try:
                    log_handle.close()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _signal_from_pid_file(self, pid_file, sig, stopped_label, missing_label, stale_label):
        if not os.path.isfile(pid_file):
            self.append_log(f"[{stopped_label}] {missing_label}\n")
            self.refresh_lsl_status(schedule=False)
            return

        try:
            with open(pid_file, "r", encoding="utf-8") as fp:
                raw = fp.read().strip()

            if not raw:
                os.remove(pid_file)
                self.append_log(f"[{stopped_label}] {stale_label}\n")
                return

            pid = int(raw)
            os.kill(pid, 0)
            os.kill(pid, sig)
            try:
                os.remove(pid_file)
            except OSError:
                pass
            self.append_log(f"[{stopped_label}] signaled PID={pid}\n")
            self.refresh_lsl_status(schedule=False)
        except ProcessLookupError:
            try:
                os.remove(pid_file)
            except OSError:
                pass
            self.append_log(f"[{stopped_label}] {stale_label}\n")
            self.refresh_lsl_status(schedule=False)
        except Exception as exc:
            self.append_log(f"[{stopped_label}] error: {exc}\n")
            self.refresh_lsl_status(schedule=False)

    def _remove_pid_file(self, pid_file):
        try:
            if os.path.isfile(pid_file):
                os.remove(pid_file)
        except OSError:
            pass

    def cleanup_managed_processes(self):
        process_specs = [
            (self.visual_pid_file, "Cleanup Visual Servo", "run_visual_servo_combined.sh"),
            (self.kinesthetic_pid_file, "Cleanup Kinesthetic", "run_gui.sh"),
            (self.state_api_pid_file, "Cleanup State API", "robot_state_api.py"),
            (self.motion_monitor_pid_file, "Cleanup Motion Monitor", "robot_motion_monitor.py"),
            (self.lsl_publisher_pid_file, "Cleanup LSL Publisher", "robot_state_publisher.py"),
        ]

        for pid_file, label, _ in process_specs:
            self._signal_from_pid_file(
                pid_file,
                signal.SIGTERM,
                label,
                f"{label.upper().replace(' ', '_')}_PID_FILE_NOT_FOUND",
                f"{label.upper().replace(' ', '_')}_STALE_PID_FILE_REMOVED",
            )

        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,args"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                for _, label, pattern in process_specs:
                    if pattern not in line:
                        continue
                    parts = line.strip().split(None, 1)
                    if not parts:
                        continue
                    pid = int(parts[0])
                    try:
                        os.kill(pid, signal.SIGTERM)
                        self.append_log(f"[{label}] signaled PID={pid}\n")
                    except ProcessLookupError:
                        pass
                    except Exception as exc:
                        self.append_log(f"[{label}] error for PID={pid}: {exc}\n")
                    break
        except Exception as exc:
            self.append_log(f"[Cleanup Managed Processes] process scan failed: {exc}\n")

        for pid_file, _, _ in process_specs:
            self._remove_pid_file(pid_file)

        self._post_state_update_async(
            "Cleanup State",
            {
                "visual_servo_active": 0,
                "kt_active": 0,
                "teaching_active": 0,
                "running_active": 0,
                "arm_moving": 0,
                "gripper_moving": 0,
            },
        )
        self.refresh_lsl_status(schedule=False)

    def _pid_is_running(self, pid_file):
        if not os.path.isfile(pid_file):
            return False
        try:
            with open(pid_file, "r", encoding="utf-8") as fp:
                raw = fp.read().strip()
            if not raw:
                return False
            os.kill(int(raw), 0)
            return True
        except Exception:
            return False

    def refresh_lsl_status(self, schedule=True):
        process_running = self._pid_is_running(self.lsl_publisher_pid_file)
        stream_visible = False

        if process_running and resolve_byprop is not None:
            try:
                streams = resolve_byprop("name", "FR3_State", timeout=0.2)
                stream_visible = bool(streams)
            except Exception:
                stream_visible = False

        if not process_running:
            status = "LSL: inactive"
            color = "#b00020"
        elif stream_visible:
            status = "LSL: active"
            color = "#0b6e3e"
        elif resolve_byprop is None:
            status = "LSL: publisher running"
            color = "#0b6e3e"
        else:
            status = "LSL: publisher running, stream not visible"
            color = "#b00020"

        self.lsl_status_text.set(status)
        self.lsl_status_label.configure(fg=color)
        if process_running:
            self.start_lsl_button.configure(state="disabled")
            self.stop_lsl_button.configure(state="normal")
        else:
            self.start_lsl_button.configure(state="normal")
            self.stop_lsl_button.configure(state="disabled")
        if schedule:
            self.root.after(1000, self.refresh_lsl_status)

    def start_visual_servo(self):
        self.ensure_state_services()
        visual_dir = self.visual_dir.get().strip()
        mode = self.visual_mode.get().strip()
        robot_ip = self.robot_ip.get().strip()
        emc_path = self.emc_path.get().strip()

        if not visual_dir:
            messagebox.showerror("Missing path", "Visual servo repository path is required.")
            return

        cmd = (
            f"cd {shlex.quote(visual_dir)} && "
            "export LD_LIBRARY_PATH=/opt/ros/humble/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH && "
            f"export MODE={shlex.quote(mode)} && "
            f"echo $$ > {shlex.quote(self.visual_pid_file)} && "
            f"exec ./run_visual_servo_combined.sh --ip {shlex.quote(robot_ip)} --eMc {shlex.quote(emc_path)}"
        )
        self._launch_local_gui_async("Start Visual Servo", cmd, "visual_proc")

    def stop_visual_servo(self):
        self._post_state_update_async("Visual Servo", {"visual_servo_active": 0})
        self._signal_from_pid_file(
            self.visual_pid_file,
            signal.SIGTERM,
            "Stop Visual Servo",
            "VISUAL_SERVO_PID_FILE_NOT_FOUND",
            "VISUAL_SERVO_STALE_PID_FILE_REMOVED",
        )

    def kill_visual_servo(self):
        self._post_state_update_async("Visual Servo", {"visual_servo_active": 0})
        self._signal_from_pid_file(
            self.visual_pid_file,
            signal.SIGKILL,
            "Kill Visual Servo",
            "VISUAL_SERVO_PID_FILE_NOT_FOUND",
            "VISUAL_SERVO_STALE_PID_FILE_REMOVED",
        )

    def start_kinesthetic(self):
        self.ensure_state_services()
        kin_dir = self.kinesthetic_dir.get().strip()
        if not kin_dir:
            messagebox.showerror("Missing path", "Kinesthetic repository path is required.")
            return

        cmd = (
            f"cd {shlex.quote(kin_dir)} && "
            f"echo $$ > {shlex.quote(self.kinesthetic_pid_file)} && "
            "exec ./run_gui.sh"
        )
        self._launch_local_gui_async("Start Kinesthetic", cmd, "kinesthetic_proc")

    def stop_kinesthetic(self):
        self._post_state_update_async("Kinesthetic", {"kt_active": 0})
        self._signal_from_pid_file(
            self.kinesthetic_pid_file,
            signal.SIGTERM,
            "Stop Kinesthetic",
            "KINESTHETIC_GUI_PID_FILE_NOT_FOUND",
            "KINESTHETIC_GUI_STALE_PID_FILE_REMOVED",
        )

    def kill_kinesthetic(self):
        self._post_state_update_async("Kinesthetic", {"kt_active": 0})
        self._signal_from_pid_file(
            self.kinesthetic_pid_file,
            signal.SIGKILL,
            "Kill Kinesthetic",
            "KINESTHETIC_GUI_PID_FILE_NOT_FOUND",
            "KINESTHETIC_GUI_STALE_PID_FILE_REMOVED",
        )

    def ensure_state_services(self):
        self._start_managed_service(
            "State API",
            self.state_api_pid_file,
            self.state_api_log_file,
            "state_api_proc",
            f"python3 {shlex.quote(os.path.join(self.base_dir, 'robot_state_api.py'))}",
        )
        self._start_managed_service(
            "Motion Monitor",
            self.motion_monitor_pid_file,
            self.motion_monitor_log_file,
            "motion_monitor_proc",
            f"python3 {shlex.quote(os.path.join(self.base_dir, 'robot_motion_monitor.py'))}",
        )
        self.refresh_lsl_status(schedule=False)

    def ensure_lsl_dependencies(self):
        self._start_managed_service(
            "State API",
            self.state_api_pid_file,
            self.state_api_log_file,
            "state_api_proc",
            f"python3 {shlex.quote(os.path.join(self.base_dir, 'robot_state_api.py'))}",
        )
        self._start_managed_service(
            "Motion Monitor",
            self.motion_monitor_pid_file,
            self.motion_monitor_log_file,
            "motion_monitor_proc",
            f"python3 {shlex.quote(os.path.join(self.base_dir, 'robot_motion_monitor.py'))}",
        )
        self.refresh_lsl_status(schedule=False)

    def start_lsl_stream(self):
        self.ensure_lsl_dependencies()
        self._start_managed_service(
            "LSL Publisher",
            self.lsl_publisher_pid_file,
            self.lsl_publisher_log_file,
            "lsl_publisher_proc",
            f"python3 {shlex.quote(os.path.join(self.base_dir, 'robot_state_publisher.py'))}",
        )
        self.refresh_lsl_status(schedule=False)

    def stop_lsl_stream(self):
        self._signal_from_pid_file(
            self.lsl_publisher_pid_file,
            signal.SIGTERM,
            "Stop LSL Publisher",
            "LSL_PUBLISHER_PID_FILE_NOT_FOUND",
            "LSL_PUBLISHER_STALE_PID_FILE_REMOVED",
        )
        self.lsl_status_text.set("LSL: inactive")

    def stop_state_services(self):
        self._signal_from_pid_file(
            self.lsl_publisher_pid_file,
            signal.SIGTERM,
            "Stop LSL Publisher",
            "LSL_PUBLISHER_PID_FILE_NOT_FOUND",
            "LSL_PUBLISHER_STALE_PID_FILE_REMOVED",
        )
        self._signal_from_pid_file(
            self.motion_monitor_pid_file,
            signal.SIGTERM,
            "Stop Motion Monitor",
            "MOTION_MONITOR_PID_FILE_NOT_FOUND",
            "MOTION_MONITOR_STALE_PID_FILE_REMOVED",
        )
        self._signal_from_pid_file(
            self.state_api_pid_file,
            signal.SIGTERM,
            "Stop State API",
            "STATE_API_PID_FILE_NOT_FOUND",
            "STATE_API_STALE_PID_FILE_REMOVED",
        )

    def kill_state_services(self):
        self._signal_from_pid_file(
            self.lsl_publisher_pid_file,
            signal.SIGKILL,
            "Kill LSL Publisher",
            "LSL_PUBLISHER_PID_FILE_NOT_FOUND",
            "LSL_PUBLISHER_STALE_PID_FILE_REMOVED",
        )
        self._signal_from_pid_file(
            self.motion_monitor_pid_file,
            signal.SIGKILL,
            "Kill Motion Monitor",
            "MOTION_MONITOR_PID_FILE_NOT_FOUND",
            "MOTION_MONITOR_STALE_PID_FILE_REMOVED",
        )
        self._signal_from_pid_file(
            self.state_api_pid_file,
            signal.SIGKILL,
            "Kill State API",
            "STATE_API_PID_FILE_NOT_FOUND",
            "STATE_API_STALE_PID_FILE_REMOVED",
        )

    def check_local_status(self):
        cmd = (
            f'echo "--- Visual Servo PID file ---"; '
            f'if [ -f {shlex.quote(self.visual_pid_file)} ]; then cat {shlex.quote(self.visual_pid_file)}; else echo "missing"; fi; '
            f'echo "--- Kinesthetic PID file ---"; '
            f'if [ -f {shlex.quote(self.kinesthetic_pid_file)} ]; then cat {shlex.quote(self.kinesthetic_pid_file)}; else echo "missing"; fi; '
            f'echo "--- State API PID file ---"; '
            f'if [ -f {shlex.quote(self.state_api_pid_file)} ]; then cat {shlex.quote(self.state_api_pid_file)}; else echo "missing"; fi; '
            f'echo "--- Motion Monitor PID file ---"; '
            f'if [ -f {shlex.quote(self.motion_monitor_pid_file)} ]; then cat {shlex.quote(self.motion_monitor_pid_file)}; else echo "missing"; fi; '
            f'echo "--- LSL Publisher PID file ---"; '
            f'if [ -f {shlex.quote(self.lsl_publisher_pid_file)} ]; then cat {shlex.quote(self.lsl_publisher_pid_file)}; else echo "missing"; fi; '
            'echo "--- Matching processes ---"; '
            'ps -ef | grep -E "servoFrankaIBVS_combined|run_visual_servo_combined.sh|franka_teach|run_gui.sh|robot_state_api.py|robot_motion_monitor.py|robot_state_publisher.py" | grep -v grep'
        )
        self._run_bash_async(cmd, "Local Status")

    def show_last_logs(self):
        cmd = (
            f'echo "--- Visual Servo Log ---"; tail -n 30 {shlex.quote(self.visual_log_file)} 2>/dev/null || echo "No visual servo log"; '
            'echo ""; '
            f'echo "--- Kinesthetic Log ---"; tail -n 30 {shlex.quote(self.kinesthetic_log_file)} 2>/dev/null || echo "No kinesthetic log"; '
            'echo ""; '
            f'echo "--- State API Log ---"; tail -n 30 {shlex.quote(self.state_api_log_file)} 2>/dev/null || echo "No state API log"; '
            'echo ""; '
            f'echo "--- Motion Monitor Log ---"; tail -n 30 {shlex.quote(self.motion_monitor_log_file)} 2>/dev/null || echo "No motion monitor log"; '
            'echo ""; '
            f'echo "--- LSL Publisher Log ---"; tail -n 30 {shlex.quote(self.lsl_publisher_log_file)} 2>/dev/null || echo "No LSL publisher log"'
        )
        self._run_bash_async(cmd, "Last Logs")

    def on_close(self):
        self.cleanup_managed_processes()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = FR3LauncherApp(root)
    root.mainloop()
