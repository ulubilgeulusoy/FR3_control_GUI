import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import shlex
import os
import json
import re
import time

import paramiko


WINDOWS_NO_CONSOLE = os.name == "nt"
WINDOWS_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SSHManager:
    def __init__(self):
        self.client = None
        self.connected = False
        self.host = ""
        self.port = 22
        self.username = ""
        self.password = ""

    def connect(self, host, port, username, password):
        self.disconnect()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=host,
            port=int(port),
            username=username,
            password=password,
            timeout=10,
            look_for_keys=False,
            allow_agent=False,
        )

        self.client = client
        self.connected = True
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password

    def exec(self, command):
        if not self.connected or self.client is None:
            raise RuntimeError("SSH is not connected.")

        stdin, stdout, stderr = self.client.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_status = stdout.channel.recv_exit_status()
        return out, err, exit_status

    def disconnect(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.connected = False

    def __del__(self):
        self.disconnect()


class FR3LauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FR3 Remote Launcher")
        self.root.geometry("950x700")

        self.ssh = SSHManager()
        self.repo_dir = os.path.dirname(os.path.abspath(__file__))
        self.xlaunch_config_path = os.path.join(self.repo_dir, "config.xlaunch")

        # SSH fields
        self.ssh_host = tk.StringVar(value="192.168.0.242")
        self.ssh_port = tk.StringVar(value="22")
        self.ssh_user = tk.StringVar(value="parc")
        self.ssh_password = tk.StringVar(value="")

        # WSL distro
        self.wsl_distro = tk.StringVar(value="Ubuntu")

        # Remote paths
        self.visual_servo_dir = tk.StringVar(value="/home/parc/FR3_visual_servo_examples")
        self.kinesthetic_dir = tk.StringVar(value="/home/parc/franka_kinesthetic_teaching_GUI")
        self.robot_state_api_path = tk.StringVar(value="/home/parc/FR3_control_GUI/robot_state_api.py")
        self.robot_motion_monitor_path = tk.StringVar(value="/home/parc/FR3_control_GUI/robot_motion_monitor.py")
        self.robot_state_publisher_path = tk.StringVar(value="/home/parc/FR3_control_GUI/robot_state_publisher.py")

        # Visual servo args
        self.robot_ip = tk.StringVar(value="172.16.0.2")
        self.eMc_path = tk.StringVar(value="config/eMc.yaml")
        self.visual_mode = tk.StringVar(value="1")

        # PID files and log files on remote machine
        self.visual_pid_file = "/tmp/fr3_visual_servo.pid"
        self.kinesthetic_pid_file = "/tmp/fr3_kinesthetic_gui.pid"
        self.robot_state_api_pid_file = "/tmp/fr3_robot_state_api.pid"
        self.robot_motion_monitor_pid_file = "/tmp/fr3_robot_motion_monitor.pid"
        self.robot_state_pid_file = "/tmp/fr3_robot_state_publisher.pid"
        self.visual_log_file = "/tmp/fr3_visual_servo.log"
        self.kinesthetic_log_file = "/tmp/fr3_kinesthetic.log"
        self.robot_state_api_log_file = "/tmp/fr3_robot_state_api.log"
        self.robot_motion_monitor_log_file = "/tmp/fr3_robot_motion_monitor.log"
        self.robot_state_log_file = "/tmp/fr3_robot_state_publisher.log"

        self.status_text = tk.StringVar(value="Not connected")
        self.x11_status_text = tk.StringVar(value="X11 inactive")
        self.continue_button = None

        self._active_scroll_canvas = None
        self.login_view, self.login_canvas, self.login_frame = self._create_scrollable_screen()
        self.control_view, self.control_canvas, self.control_frame = self._create_scrollable_screen()
        self.root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_mousewheel_linux, add="+")
        self.root.bind_all("<Button-5>", self._on_mousewheel_linux, add="+")

        self.visual_wsl_proc = None
        self.kinesthetic_wsl_proc = None
        self._last_visual_servo_motion_pulse = 0.0
        self._visual_servo_motion_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in [
                r"\bservo\b",
                r"\btracking\b",
                r"\btag\b",
                r"\bpose\b",
                r"\bvelocity\b",
                r"\btwist\b",
                r"\bcontrol\b",
                r"\berror\b",
                r"\bdetected\b",
                r"\bconvergen",
            ]
        ]

        self._build_login_frame()
        self._build_control_frame()

        self.show_login_frame()
        self._schedule_x11_status_poll()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _subprocess_kwargs(self):
        if not WINDOWS_NO_CONSOLE:
            return {}

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {
            "startupinfo": startupinfo,
            "creationflags": WINDOWS_CREATE_NO_WINDOW,
        }

    def _create_scrollable_screen(self):
        container = ttk.Frame(self.root)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=15)

        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        content.bind(
            "<Configure>",
            lambda _event, c=canvas: c.configure(scrollregion=c.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event, c=canvas, w=window_id: c.itemconfigure(w, width=event.width),
        )

        for widget in (container, canvas, content):
            widget.bind("<Enter>", lambda _event, c=canvas: self._set_active_scroll_canvas(c), add="+")

        return container, canvas, content

    def _set_active_scroll_canvas(self, canvas):
        self._active_scroll_canvas = canvas

    def _scroll_active_canvas(self, units):
        canvas = self._active_scroll_canvas
        if canvas is None:
            return
        if canvas.bbox("all") is None:
            return
        canvas.yview_scroll(units, "units")

    def _on_mousewheel(self, event):
        if self._active_scroll_canvas is None:
            return
        delta = event.delta
        if delta == 0:
            return
        step = -1 if delta > 0 else 1
        self._scroll_active_canvas(step)

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self._scroll_active_canvas(-1)
        elif event.num == 5:
            self._scroll_active_canvas(1)

    def _build_login_frame(self):
        frame = self.login_frame

        title = ttk.Label(frame, text="FR3 SSH Connection", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w", pady=(0, 15))

        fields = ttk.LabelFrame(frame, text="SSH Info", padding=12)
        fields.pack(fill="x", pady=(0, 15))

        ttk.Label(fields, text="Host").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(fields, textvariable=self.ssh_host, width=30).grid(row=0, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(fields, text="Port").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(fields, textvariable=self.ssh_port, width=30).grid(row=1, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(fields, text="Username").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(fields, textvariable=self.ssh_user, width=30).grid(row=2, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(fields, text="Password").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(fields, textvariable=self.ssh_password, width=30, show="*").grid(row=3, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(fields, text="WSL Distro").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(fields, textvariable=self.wsl_distro, width=30).grid(row=4, column=1, sticky="ew", padx=8, pady=5)

        fields.columnconfigure(1, weight=1)

        remote = ttk.LabelFrame(frame, text="Remote Paths and Args", padding=12)
        remote.pack(fill="x", pady=(0, 15))

        ttk.Label(remote, text="Visual Servo Repo").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.visual_servo_dir).grid(row=0, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="Kinesthetic Repo").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.kinesthetic_dir).grid(row=1, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="State API").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.robot_state_api_path).grid(row=2, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="Motion Monitor").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.robot_motion_monitor_path).grid(row=3, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="State Publisher").grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.robot_state_publisher_path).grid(row=4, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="Robot IP").grid(row=5, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.robot_ip).grid(row=5, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="eMc Path").grid(row=6, column=0, sticky="w", pady=5)
        ttk.Entry(remote, textvariable=self.eMc_path).grid(row=6, column=1, sticky="ew", padx=8, pady=5)

        ttk.Label(remote, text="Visual Mode").grid(row=7, column=0, sticky="w", pady=5)
        ttk.Combobox(
            remote,
            textvariable=self.visual_mode,
            values=["1", "2"],
            state="readonly",
            width=8
        ).grid(row=7, column=1, sticky="w", padx=8, pady=5)

        remote.columnconfigure(1, weight=1)

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")

        self.ssh_status_label = ttk.Label(bottom, textvariable=self.status_text, foreground="red")
        self.ssh_status_label.pack(side="left")
        ttk.Button(bottom, text="Test Connection", command=self.test_connection).pack(side="right", padx=(8, 0))
        self.continue_button = ttk.Button(bottom, text="Continue", command=self.continue_to_controls)
        self.continue_button.pack(side="right")
        ttk.Button(bottom, text="Disconnect SSH", command=self.disconnect_ssh).pack(side="right", padx=(0, 8))

        x11_box = ttk.LabelFrame(frame, text="Display Server", padding=12)
        x11_box.pack(fill="x", pady=(12, 0))

        x11_buttons = ttk.Frame(x11_box)
        x11_buttons.pack(anchor="w")

        ttk.Button(x11_buttons, text="Activate X11", command=self.activate_x11).pack(side="left")
        ttk.Button(x11_buttons, text="Disconnect X11", command=self.deactivate_x11).pack(side="left", padx=(8, 0))
        ttk.Label(
            x11_box,
            text="Starts the saved X11/VcXsrv configuration used so remote GUI windows can open on this computer.",
        ).pack(anchor="w", pady=(6, 2))
        self.x11_status_label = ttk.Label(x11_box, textvariable=self.x11_status_text, foreground="red")
        self.x11_status_label.pack(anchor="w")

    def _build_control_frame(self):
        frame = self.control_frame

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="FR3 Control Interface", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.status_text).pack(side="right")

        button_area = ttk.Frame(frame)
        button_area.pack(fill="x", pady=(0, 10))

        visual_box = ttk.LabelFrame(button_area, text="Visual Servoing", padding=12)
        visual_box.pack(side="left", fill="both", expand=True, padx=(0, 5))

        ttk.Button(visual_box, text="Start Visual Servo", command=self.start_visual_servo).pack(fill="x", pady=4)
        ttk.Button(visual_box, text="Quit Visual Servo", command=self.kill_visual_servo).pack(fill="x", pady=4)

        kin_box = ttk.LabelFrame(button_area, text="Kinesthetic Teaching", padding=12)
        kin_box.pack(side="left", fill="both", expand=True, padx=(5, 0))

        ttk.Button(kin_box, text="Start Kinesthetic GUI", command=self.start_kinesthetic).pack(fill="x", pady=4)
        ttk.Button(kin_box, text="Quit Kinesthetic GUI", command=self.kill_kinesthetic).pack(fill="x", pady=4)

        tools = ttk.Frame(frame)
        tools.pack(fill="x", pady=(0, 10))

        ttk.Button(tools, text="Check Remote Status", command=self.check_remote_status).pack(side="left")
        ttk.Button(tools, text="Show Last Logs", command=self.show_last_logs).pack(side="left", padx=8)
        ttk.Button(tools, text="Debug LSL Status", command=self.debug_lsl_status).pack(side="left")
        ttk.Button(tools, text="Back", command=self.show_login_frame).pack(side="right")
        ttk.Button(tools, text="Disconnect", command=self.disconnect_ssh).pack(side="right", padx=(0, 8))

        info = ttk.Label(
            frame,
            text="Start buttons use WSL + ssh -Y so the existing GUIs open on your laptop."
        )
        info.pack(anchor="w", pady=(0, 8))

        log_box = ttk.LabelFrame(frame, text="Log", padding=10)
        log_box.pack(fill="both", expand=True)

        self.log_text = scrolledtext.ScrolledText(log_box, wrap="word", height=25)
        self.log_text.pack(fill="both", expand=True)

    def show_login_frame(self):
        self.control_view.pack_forget()
        self.login_view.pack(fill="both", expand=True)
        self.login_canvas.yview_moveto(0)
        self._set_active_scroll_canvas(self.login_canvas)
        self.refresh_x11_status()

    def show_control_frame(self):
        self.login_view.pack_forget()
        self.control_view.pack(fill="both", expand=True)
        self.control_canvas.yview_moveto(0)
        self._set_active_scroll_canvas(self.control_canvas)
        self.refresh_x11_status()

    def append_log(self, text):
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def run_ssh_command_async(self, command, label=None):
        def worker():
            try:
                out, err, code = self.ssh.exec(command)
                msg = ""
                if label:
                    msg += f"[{label}] exit={code}\n"
                if out:
                    msg += out
                    if not out.endswith("\n"):
                        msg += "\n"
                if err:
                    msg += err
                    if not err.endswith("\n"):
                        msg += "\n"
                if not out and not err:
                    msg += "(no output)\n"
                self.root.after(0, lambda: self.append_log(msg))
            except Exception as e:
                self.root.after(0, lambda: self.append_log(f"[ERROR] {e}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def run_ssh_command_silent_async(self, command):
        def worker():
            try:
                self.ssh.exec(command)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _build_robot_state_api_post_command(self, payload):
        payload_json = json.dumps(payload)
        return (
            "bash -lc "
            + shlex.quote(
                "python3 -c "
                + shlex.quote(
                    "import json, urllib.request; "
                    f"data = {payload_json!r}.encode('utf-8'); "
                    "req = urllib.request.Request("
                    "'http://127.0.0.1:8765/state', "
                    "data=data, "
                    "headers={'Content-Type': 'application/json'}, "
                    "method='POST'); "
                    "urllib.request.urlopen(req, timeout=0.2).read()"
                )
            )
        )

    def post_robot_state_update_async(self, payload):
        if not self.ssh.connected:
            return
        self.run_ssh_command_silent_async(self._build_robot_state_api_post_command(payload))

    def handle_visual_servo_output_line(self, line):
        lowered = line.strip().lower()
        if not lowered:
            return

        ignore_fragments = [
            "built target",
            "configuring done",
            "generating done",
            "build files have been written",
            "camera parameters",
            "factory parameters",
            "apriltag",
            "e_m_c",
            "warning: no xauth data",
        ]
        if any(fragment in lowered for fragment in ignore_fragments):
            return

        if not any(pattern.search(lowered) for pattern in self._visual_servo_motion_patterns):
            return

        now = time.monotonic()
        if now - self._last_visual_servo_motion_pulse < 0.25:
            return

        self._last_visual_servo_motion_pulse = now
        self.post_robot_state_update_async({"arm_moving": 1, "ttl_sec": 0.5})

    def _test_sshpass_in_wsl(self):
        distro = self.wsl_distro.get().strip()
        cmd = ["wsl.exe", "-d", distro, "-e", "bash", "-lc", "command -v sshpass >/dev/null 2>&1"]
        result = subprocess.run(cmd, capture_output=True, text=True, **self._subprocess_kwargs())
        return result.returncode == 0

    def _is_x11_process_running(self):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq vcxsrv.exe"],
                capture_output=True,
                text=True,
                timeout=5,
                **self._subprocess_kwargs(),
            )
            return result.returncode == 0 and "vcxsrv.exe" in result.stdout.lower()
        except Exception:
            return False

    def refresh_x11_status(self):
        x11_active = self._is_x11_process_running()
        self.x11_status_text.set("X11 active" if x11_active else "X11 inactive")
        if hasattr(self, "x11_status_label"):
            self.x11_status_label.config(foreground="green" if x11_active else "red")
        self._update_continue_state()

    def _schedule_x11_status_poll(self):
        self.refresh_x11_status()
        self.root.after(2000, self._schedule_x11_status_poll)

    def _update_continue_state(self):
        if self.continue_button is None:
            return

        is_ready = self.ssh.connected and self._is_x11_process_running()
        self.continue_button.config(state="normal" if is_ready else "disabled")
        if hasattr(self, "ssh_status_label"):
            status = self.status_text.get().strip().lower()
            if self.ssh.connected:
                color = "green"
            elif "connecting" in status:
                color = "orange"
            else:
                color = "red"
            self.ssh_status_label.config(foreground=color)

    def activate_x11(self):
        def worker():
            try:
                if self._is_x11_process_running():
                    self.root.after(0, lambda: self.x11_status_text.set("X11 active"))
                    self.root.after(0, lambda: self.append_log("[X11] already active.\n"))
                    return

                if not os.path.isfile(self.xlaunch_config_path):
                    self.root.after(0, lambda: messagebox.showerror("X11 Config Missing", f"Could not find:\n{self.xlaunch_config_path}"))
                    return

                os.startfile(self.xlaunch_config_path)
                self.root.after(0, lambda: self.append_log(f"[X11] launched config: {self.xlaunch_config_path}\n"))
                self.root.after(1500, self.refresh_x11_status)
            except Exception as e:
                self.root.after(0, lambda: self.x11_status_text.set("X11 inactive"))
                self.root.after(0, lambda: self.append_log(f"[X11] launch error: {e}\n"))

        threading.Thread(target=worker, daemon=True).start()

    def deactivate_x11(self):
        def worker():
            try:
                if not self._is_x11_process_running():
                    self.root.after(0, lambda: self.x11_status_text.set("X11 inactive"))
                    self.root.after(0, lambda: self.append_log("[X11] already inactive.\n"))
                    return

                result = subprocess.run(
                    ["taskkill", "/F", "/IM", "vcxsrv.exe"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    **self._subprocess_kwargs(),
                )

                if result.returncode == 0:
                    self.root.after(0, lambda: self.append_log("[X11] disconnected.\n"))
                else:
                    details = (result.stdout or result.stderr).strip() or "taskkill failed"
                    self.root.after(0, lambda: self.append_log(f"[X11] disconnect error: {details}\n"))

                self.root.after(0, self.refresh_x11_status)
            except Exception as e:
                self.root.after(0, lambda: self.append_log(f"[X11] disconnect error: {e}\n"))
                self.root.after(0, self.refresh_x11_status)

        threading.Thread(target=worker, daemon=True).start()

    def _build_wsl_ssh_gui_command(self, remote_inner_command):
        distro = self.wsl_distro.get().strip()
        host = self.ssh_host.get().strip()
        port = self.ssh_port.get().strip()
        user = self.ssh_user.get().strip()
        password = self.ssh_password.get()

        remote_bash = f"bash -lc {shlex.quote(remote_inner_command)}"

        wsl_script = (
            "export DISPLAY=$(grep nameserver /etc/resolv.conf | awk '{print $2}'):0.0 && "
            f"sshpass -p {shlex.quote(password)} "
            f"ssh -Y -o StrictHostKeyChecking=no -p {shlex.quote(port)} "
            f"{shlex.quote(user)}@{shlex.quote(host)} "
            f"{shlex.quote(remote_bash)}"
        )

        return ["wsl.exe", "-d", distro, "-e", "bash", "-lc", wsl_script]

    def _launch_wsl_gui_async(self, label, command_list, proc_attr_name):
        def worker():
            try:
                existing = getattr(self, proc_attr_name)
                if existing is not None and existing.poll() is None:
                    self.root.after(0, lambda: self.append_log(f"[{label}] already running locally.\n"))
                    return

                proc = subprocess.Popen(
                    command_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    **self._subprocess_kwargs(),
                )
                setattr(self, proc_attr_name, proc)

                self.root.after(0, lambda: self.append_log(f"[{label}] launched via WSL/X11.\n"))

                for line in proc.stdout:
                    if label == "Start Visual Servo":
                        self.handle_visual_servo_output_line(line)
                    self.root.after(0, lambda ln=line: self.append_log(f"[{label}] {ln}"))

                rc = proc.wait()
                self.root.after(0, lambda: self.append_log(f"[{label}] exited with code {rc}\n"))
            except Exception as e:
                self.root.after(0, lambda: self.append_log(f"[{label}] launch error: {e}\n"))
            finally:
                setattr(self, proc_attr_name, None)

        threading.Thread(target=worker, daemon=True).start()

    def _build_remote_signal_command(self, pid_file, signal_name, stopped_label, missing_label, stale_label):
        return (
            "bash -lc '"
            f"if [ ! -f {shlex.quote(pid_file)} ]; then "
            f'echo "{missing_label}"; '
            "else "
            f"PID=$(cat {shlex.quote(pid_file)}); "
            "if [ -z \"$PID\" ]; then "
            f"rm -f {shlex.quote(pid_file)}; "
            f'echo "{stale_label}"; '
            "elif kill -0 \"$PID\" 2>/dev/null; then "
            f"kill -{signal_name} \"$PID\" && "
            f"rm -f {shlex.quote(pid_file)} && "
            f'echo "{stopped_label} PID=$PID"; '
            "else "
            f"rm -f {shlex.quote(pid_file)}; "
            f'echo "{stale_label} PID=$PID"; '
            "fi; "
            "fi'"
        )

    def _build_robot_state_cleanup_command(self):
        publisher_path = shlex.quote(self.robot_state_publisher_path.get().strip())

        return (
            "bash -lc '"
            f"PID_FILE={shlex.quote(self.robot_state_pid_file)}; "
            f"SCRIPT={publisher_path}; "
            "STOPPED=0; "
            "if [ -f \"$PID_FILE\" ]; then "
            "PID=$(cat \"$PID_FILE\"); "
            "if [ -n \"$PID\" ] && kill -0 \"$PID\" 2>/dev/null; then "
            "kill -TERM \"$PID\" 2>/dev/null || true; "
            "sleep 1; "
            "if kill -0 \"$PID\" 2>/dev/null; then "
            "kill -KILL \"$PID\" 2>/dev/null || true; "
            "fi; "
            "STOPPED=1; "
            "fi; "
            "rm -f \"$PID_FILE\"; "
            "fi; "
            "PIDS=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$PIDS\" ]; then "
            "printf \"%s\n\" \"$PIDS\" | xargs -r kill -TERM 2>/dev/null || true; "
            "sleep 1; "
            "REMAINING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$REMAINING\" ]; then "
            "printf \"%s\n\" \"$REMAINING\" | xargs -r kill -KILL 2>/dev/null || true; "
            "fi; "
            "STOPPED=1; "
            "fi; "
            "if [ \"$STOPPED\" -eq 1 ]; then "
            'echo "ROBOT_STATE_PUBLISHER_CLEANED_UP"; '
            "else "
            'echo "ROBOT_STATE_PUBLISHER_NOT_RUNNING"; '
            "fi'"
        )

    def _build_robot_state_api_cleanup_command(self):
        api_path = shlex.quote(self.robot_state_api_path.get().strip())

        return (
            "bash -lc '"
            f"PID_FILE={shlex.quote(self.robot_state_api_pid_file)}; "
            f"SCRIPT={api_path}; "
            "STOPPED=0; "
            "if [ -f \"$PID_FILE\" ]; then "
            "PID=$(cat \"$PID_FILE\"); "
            "if [ -n \"$PID\" ] && kill -0 \"$PID\" 2>/dev/null; then "
            "kill -TERM \"$PID\" 2>/dev/null || true; "
            "sleep 1; "
            "if kill -0 \"$PID\" 2>/dev/null; then "
            "kill -KILL \"$PID\" 2>/dev/null || true; "
            "fi; "
            "STOPPED=1; "
            "fi; "
            "rm -f \"$PID_FILE\"; "
            "fi; "
            "PIDS=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$PIDS\" ]; then "
            "printf \"%s\n\" \"$PIDS\" | xargs -r kill -TERM 2>/dev/null || true; "
            "sleep 1; "
            "REMAINING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$REMAINING\" ]; then "
            "printf \"%s\n\" \"$REMAINING\" | xargs -r kill -KILL 2>/dev/null || true; "
            "fi; "
            "STOPPED=1; "
            "fi; "
            "if [ \"$STOPPED\" -eq 1 ]; then "
            'echo "ROBOT_STATE_API_CLEANED_UP"; '
            "else "
            'echo "ROBOT_STATE_API_NOT_RUNNING"; '
            "fi'"
        )

    def _build_robot_state_api_start_command(self):
        api_path = shlex.quote(self.robot_state_api_path.get().strip())

        return (
            "bash -lc '"
            f"PID_FILE={shlex.quote(self.robot_state_api_pid_file)}; "
            f"LOG_FILE={shlex.quote(self.robot_state_api_log_file)}; "
            f"SCRIPT={api_path}; "
            "if [ ! -f \"$SCRIPT\" ]; then "
            'echo "ROBOT_STATE_API_SCRIPT_NOT_FOUND"; '
            "exit 1; "
            "fi; "
            "if [ -f \"$PID_FILE\" ]; then "
            "OLD_PID=$(cat \"$PID_FILE\"); "
            "if [ -n \"$OLD_PID\" ] && kill -0 \"$OLD_PID\" 2>/dev/null; then "
            "kill -TERM \"$OLD_PID\" 2>/dev/null || true; "
            "sleep 1; "
            "if kill -0 \"$OLD_PID\" 2>/dev/null; then "
            "kill -KILL \"$OLD_PID\" 2>/dev/null || true; "
            "fi; "
            "fi; "
            "rm -f \"$PID_FILE\"; "
            "fi; "
            "EXISTING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$EXISTING\" ]; then "
            "printf \"%s\n\" \"$EXISTING\" | xargs -r kill -TERM 2>/dev/null || true; "
            "sleep 1; "
            "REMAINING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$REMAINING\" ]; then "
            "printf \"%s\n\" \"$REMAINING\" | xargs -r kill -KILL 2>/dev/null || true; "
            "fi; "
            "fi; "
            "nohup python3 \"$SCRIPT\" > \"$LOG_FILE\" 2>&1 < /dev/null & "
            "PID=$!; "
            "echo \"$PID\" > \"$PID_FILE\"; "
            "sleep 1; "
            "if kill -0 \"$PID\" 2>/dev/null; then "
            'echo "ROBOT_STATE_API_STARTED PID=$PID"; '
            "else "
            "rm -f \"$PID_FILE\"; "
            'echo "ROBOT_STATE_API_FAILED_TO_START"; '
            "exit 1; "
            "fi'"
        )

    def _build_robot_motion_monitor_cleanup_command(self):
        monitor_path = shlex.quote(self.robot_motion_monitor_path.get().strip())

        return (
            "bash -lc '"
            f"PID_FILE={shlex.quote(self.robot_motion_monitor_pid_file)}; "
            f"SCRIPT={monitor_path}; "
            "STOPPED=0; "
            "if [ -f \"$PID_FILE\" ]; then "
            "PID=$(cat \"$PID_FILE\"); "
            "if [ -n \"$PID\" ] && kill -0 \"$PID\" 2>/dev/null; then "
            "kill -TERM \"$PID\" 2>/dev/null || true; "
            "sleep 1; "
            "if kill -0 \"$PID\" 2>/dev/null; then "
            "kill -KILL \"$PID\" 2>/dev/null || true; "
            "fi; "
            "STOPPED=1; "
            "fi; "
            "rm -f \"$PID_FILE\"; "
            "fi; "
            "PIDS=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$PIDS\" ]; then "
            "printf \"%s\n\" \"$PIDS\" | xargs -r kill -TERM 2>/dev/null || true; "
            "sleep 1; "
            "REMAINING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$REMAINING\" ]; then "
            "printf \"%s\n\" \"$REMAINING\" | xargs -r kill -KILL 2>/dev/null || true; "
            "fi; "
            "STOPPED=1; "
            "fi; "
            "if [ \"$STOPPED\" -eq 1 ]; then "
            'echo "ROBOT_MOTION_MONITOR_CLEANED_UP"; '
            "else "
            'echo "ROBOT_MOTION_MONITOR_NOT_RUNNING"; '
            "fi'"
        )

    def _build_robot_motion_monitor_start_command(self):
        monitor_path = shlex.quote(self.robot_motion_monitor_path.get().strip())

        return (
            "bash -lc '"
            f"PID_FILE={shlex.quote(self.robot_motion_monitor_pid_file)}; "
            f"LOG_FILE={shlex.quote(self.robot_motion_monitor_log_file)}; "
            f"SCRIPT={monitor_path}; "
            "if [ ! -f \"$SCRIPT\" ]; then "
            'echo "ROBOT_MOTION_MONITOR_SCRIPT_NOT_FOUND"; '
            "exit 1; "
            "fi; "
            "if [ -f \"$PID_FILE\" ]; then "
            "OLD_PID=$(cat \"$PID_FILE\"); "
            "if [ -n \"$OLD_PID\" ] && kill -0 \"$OLD_PID\" 2>/dev/null; then "
            "kill -TERM \"$OLD_PID\" 2>/dev/null || true; "
            "sleep 1; "
            "if kill -0 \"$OLD_PID\" 2>/dev/null; then "
            "kill -KILL \"$OLD_PID\" 2>/dev/null || true; "
            "fi; "
            "fi; "
            "rm -f \"$PID_FILE\"; "
            "fi; "
            "EXISTING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$EXISTING\" ]; then "
            "printf \"%s\n\" \"$EXISTING\" | xargs -r kill -TERM 2>/dev/null || true; "
            "sleep 1; "
            "REMAINING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$REMAINING\" ]; then "
            "printf \"%s\n\" \"$REMAINING\" | xargs -r kill -KILL 2>/dev/null || true; "
            "fi; "
            "fi; "
            "source /opt/ros/jazzy/setup.bash && "
            "nohup python3 \"$SCRIPT\" > \"$LOG_FILE\" 2>&1 < /dev/null & "
            "PID=$!; "
            "echo \"$PID\" > \"$PID_FILE\"; "
            "sleep 1; "
            "if kill -0 \"$PID\" 2>/dev/null; then "
            'echo "ROBOT_MOTION_MONITOR_STARTED PID=$PID"; '
            "else "
            "rm -f \"$PID_FILE\"; "
            'echo "ROBOT_MOTION_MONITOR_FAILED_TO_START"; '
            "exit 1; "
            "fi'"
        )

    def _build_robot_state_start_command(self):
        publisher_path = shlex.quote(self.robot_state_publisher_path.get().strip())

        return (
            "bash -lc '"
            f"PID_FILE={shlex.quote(self.robot_state_pid_file)}; "
            f"LOG_FILE={shlex.quote(self.robot_state_log_file)}; "
            f"SCRIPT={publisher_path}; "
            "if [ ! -f \"$SCRIPT\" ]; then "
            'echo "ROBOT_STATE_PUBLISHER_SCRIPT_NOT_FOUND"; '
            "exit 1; "
            "fi; "
            "if [ -f \"$PID_FILE\" ]; then "
            "OLD_PID=$(cat \"$PID_FILE\"); "
            "if [ -n \"$OLD_PID\" ] && kill -0 \"$OLD_PID\" 2>/dev/null; then "
            "kill -TERM \"$OLD_PID\" 2>/dev/null || true; "
            "sleep 1; "
            "if kill -0 \"$OLD_PID\" 2>/dev/null; then "
            "kill -KILL \"$OLD_PID\" 2>/dev/null || true; "
            "fi; "
            "fi; "
            "rm -f \"$PID_FILE\"; "
            "fi; "
            "EXISTING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$EXISTING\" ]; then "
            "printf \"%s\n\" \"$EXISTING\" | xargs -r kill -TERM 2>/dev/null || true; "
            "sleep 1; "
            "REMAINING=$(ps -eo pid=,comm=,args= | "
            "while read -r PID COMM ARGS; do "
            "if [[ \"$COMM\" =~ ^python(3(\\.[0-9]+)?)?$ ]] && [[ \"$ARGS\" == *\"$SCRIPT\"* ]]; then "
            "echo \"$PID\"; "
            "fi; "
            "done || true); "
            "if [ -n \"$REMAINING\" ]; then "
            "printf \"%s\n\" \"$REMAINING\" | xargs -r kill -KILL 2>/dev/null || true; "
            "fi; "
            "fi; "
            "source /opt/ros/jazzy/setup.bash && "
            "nohup python3 \"$SCRIPT\" > \"$LOG_FILE\" 2>&1 < /dev/null & "
            "PID=$!; "
            "echo \"$PID\" > \"$PID_FILE\"; "
            "sleep 1; "
            "if kill -0 \"$PID\" 2>/dev/null; then "
            'echo "ROBOT_STATE_PUBLISHER_STARTED PID=$PID"; '
            "else "
            "rm -f \"$PID_FILE\"; "
            'echo "ROBOT_STATE_PUBLISHER_FAILED_TO_START"; '
            "exit 1; "
            "fi'"
        )

    def ensure_robot_state_publisher_running(self):
        if not self.ssh.connected:
            return
        self.run_ssh_command_async(self._build_robot_state_api_start_command(), "Robot State API")
        self.run_ssh_command_async(self._build_robot_motion_monitor_start_command(), "Robot Motion Monitor")
        self.run_ssh_command_async(self._build_robot_state_start_command(), "Robot State Publisher")

    def _stop_robot_state_publisher_before_disconnect(self):
        if not self.ssh.connected:
            return

        try:
            self.ssh.exec(self._build_robot_state_cleanup_command())
            self.ssh.exec(self._build_robot_motion_monitor_cleanup_command())
            self.ssh.exec(self._build_robot_state_api_cleanup_command())
        except Exception:
            pass

    def test_connection(self):
        host = self.ssh_host.get().strip()
        port = self.ssh_port.get().strip()
        user = self.ssh_user.get().strip()
        password = self.ssh_password.get()

        if not host or not port or not user:
            messagebox.showerror("Missing info", "Please fill host, port, username, and password.")
            return

        self.status_text.set("Connecting...")
        self._update_continue_state()

        def worker():
            try:
                self.ssh.connect(host, port, user, password)
                out, err, code = self.ssh.exec("echo SSH_OK && hostname && pwd")
                msg = f"{out}{err}"

                if not self._test_sshpass_in_wsl():
                    extra = (
                        "\n\nWSL does not have sshpass installed yet.\n"
                        "Run this in WSL once:\n"
                        "sudo apt update && sudo apt install sshpass -y"
                    )
                else:
                    extra = "\n\nWSL sshpass check passed."

                self.root.after(0, lambda: self.status_text.set(f"Connected to {host} as {user}"))
                self.root.after(0, self._update_continue_state)
                self.root.after(0, lambda: messagebox.showinfo("Success", (msg.strip() or "SSH connection successful.") + extra))
            except Exception as e:
                self.root.after(0, lambda: self.status_text.set("Connection failed"))
                self.root.after(0, self._update_continue_state)
                self.root.after(0, lambda: messagebox.showerror("SSH Error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def continue_to_controls(self):
        if not self.ssh.connected:
            messagebox.showwarning("Not connected", "Please test and establish SSH connection first.")
            return
        if not self._is_x11_process_running():
            messagebox.showwarning("X11 inactive", "Please activate X11 before continuing.")
            self.refresh_x11_status()
            return
        self.show_control_frame()
        self.append_log("[INFO] Entered control interface.\n")
        self.ensure_robot_state_publisher_running()

    def disconnect_ssh(self):
        self._stop_robot_state_publisher_before_disconnect()
        self.ssh.disconnect()
        self.status_text.set("Disconnected")
        self._update_continue_state()
        self.append_log("[INFO] SSH disconnected.\n")

    def start_visual_servo(self):
        if not self._test_sshpass_in_wsl():
            messagebox.showerror(
                "Missing sshpass in WSL",
                "Install sshpass in WSL first:\n\nsudo apt update && sudo apt install sshpass -y"
            )
            return

        remote_cmd = (
            "source /opt/ros/jazzy/setup.bash && "
            "export LD_LIBRARY_PATH=/opt/ros/jazzy/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH && "
            f"cd {shlex.quote(self.visual_servo_dir.get().strip())} && "
            f"export MODE={shlex.quote(self.visual_mode.get().strip())} && "
            f"echo $$ > {shlex.quote(self.visual_pid_file)} && "
            f"exec ./run_visual_servo_combined.sh --ip {shlex.quote(self.robot_ip.get().strip())} --eMc {shlex.quote(self.eMc_path.get().strip())}"
        )

        cmd = self._build_wsl_ssh_gui_command(remote_cmd)
        self._launch_wsl_gui_async("Start Visual Servo", cmd, "visual_wsl_proc")

    def stop_visual_servo(self):
        cmd = self._build_remote_signal_command(
            self.visual_pid_file,
            "TERM",
            "VISUAL_SERVO_STOPPED",
            "VISUAL_SERVO_PID_FILE_NOT_FOUND",
            "VISUAL_SERVO_STALE_PID_FILE_REMOVED",
        )
        self.run_ssh_command_async(cmd, "Stop Visual Servo")

    def kill_visual_servo(self):
        cmd = self._build_remote_signal_command(
            self.visual_pid_file,
            "KILL",
            "VISUAL_SERVO_KILLED",
            "VISUAL_SERVO_PID_FILE_NOT_FOUND",
            "VISUAL_SERVO_STALE_PID_FILE_REMOVED",
        )
        self.run_ssh_command_async(cmd, "Kill Visual Servo")

    def start_kinesthetic(self):
        if not self._test_sshpass_in_wsl():
            messagebox.showerror(
                "Missing sshpass in WSL",
                "Install sshpass in WSL first:\n\nsudo apt update && sudo apt install sshpass -y"
            )
            return

        remote_cmd = (
            "source /opt/ros/jazzy/setup.bash && "
            f"cd {shlex.quote(self.kinesthetic_dir.get().strip())} && "
            f"echo $$ > {shlex.quote(self.kinesthetic_pid_file)} && "
            "exec ./run_gui.sh"
        )

        cmd = self._build_wsl_ssh_gui_command(remote_cmd)
        self._launch_wsl_gui_async("Start Kinesthetic", cmd, "kinesthetic_wsl_proc")

    def stop_kinesthetic(self):
        cmd = self._build_remote_signal_command(
            self.kinesthetic_pid_file,
            "TERM",
            "KINESTHETIC_GUI_STOPPED",
            "KINESTHETIC_GUI_PID_FILE_NOT_FOUND",
            "KINESTHETIC_GUI_STALE_PID_FILE_REMOVED",
        )
        self.run_ssh_command_async(cmd, "Stop Kinesthetic")

    def kill_kinesthetic(self):
        cmd = self._build_remote_signal_command(
            self.kinesthetic_pid_file,
            "KILL",
            "KINESTHETIC_GUI_KILLED",
            "KINESTHETIC_GUI_PID_FILE_NOT_FOUND",
            "KINESTHETIC_GUI_STALE_PID_FILE_REMOVED",
        )
        self.run_ssh_command_async(cmd, "Kill Kinesthetic")

    def check_remote_status(self):
        cmd = (
            "bash -lc '"
            f'echo "--- Visual Servo PID file ---"; '
            f'if [ -f {self.visual_pid_file} ]; then cat {self.visual_pid_file}; else echo "missing"; fi; '
            f'echo "--- Kinesthetic PID file ---"; '
            f'if [ -f {self.kinesthetic_pid_file} ]; then cat {self.kinesthetic_pid_file}; else echo "missing"; fi; '
            f'echo "--- Robot State Publisher PID file ---"; '
            f'if [ -f {self.robot_state_pid_file} ]; then cat {self.robot_state_pid_file}; else echo "missing"; fi; '
            f'echo "--- Robot State API PID file ---"; '
            f'if [ -f {self.robot_state_api_pid_file} ]; then cat {self.robot_state_api_pid_file}; else echo "missing"; fi; '
            f'echo "--- Robot Motion Monitor PID file ---"; '
            f'if [ -f {self.robot_motion_monitor_pid_file} ]; then cat {self.robot_motion_monitor_pid_file}; else echo "missing"; fi; '
            "echo \"--- Matching processes ---\"; "
            "ps -ef | grep -E \"servoFrankaIBVS_combined|run_visual_servo_combined.sh|franka_teach|run_gui.sh|robot_state_publisher.py|robot_state_api.py|robot_motion_monitor.py\" | grep -v grep'"
        )
        self.run_ssh_command_async(cmd, "Remote Status")

    def show_last_logs(self):
        cmd = (
            "bash -lc '"
            f'echo "--- Visual Servo Log ---"; '
            f'tail -n 30 {self.visual_log_file} 2>/dev/null || echo "No visual servo log"; '
            f'echo ""; '
            f'echo "--- Kinesthetic Log ---"; '
            f'tail -n 30 {self.kinesthetic_log_file} 2>/dev/null || echo "No kinesthetic log"; '
            f'echo ""; '
            f'echo "--- Robot State Publisher Log ---"; '
            f'tail -n 30 {self.robot_state_log_file} 2>/dev/null || echo "No robot state publisher log"; '
            f'echo ""; '
            f'echo "--- Robot State API Log ---"; '
            f'tail -n 30 {self.robot_state_api_log_file} 2>/dev/null || echo "No robot state api log"; '
            f'echo ""; '
            f'echo "--- Robot Motion Monitor Log ---"; '
            f'tail -n 30 {self.robot_motion_monitor_log_file} 2>/dev/null || echo "No robot motion monitor log"'
            "'"
        )
        self.run_ssh_command_async(cmd, "Last Logs")

    def debug_lsl_status(self):
        cmd = (
            "bash -lc '"
            "source /opt/ros/jazzy/setup.bash >/dev/null 2>&1 || true; "
            f'echo "--- Kinesthetic PID file ---"; '
            f'if [ -f {shlex.quote(self.kinesthetic_pid_file)} ]; then cat {shlex.quote(self.kinesthetic_pid_file)}; else echo "missing"; fi; '
            f'echo "--- Visual PID file ---"; '
            f'if [ -f {shlex.quote(self.visual_pid_file)} ]; then cat {shlex.quote(self.visual_pid_file)}; else echo "missing"; fi; '
            'echo "--- Matching kinesthetic processes ---"; '
            "ps -ef | grep -E \"run_gui.sh|franka_teach|kinesthetic\" | grep -v grep || echo \"none\"; "
            'echo "--- Matching visual-servo processes ---"; '
            "ps -ef | grep -E \"servoFrankaIBVS_combined|run_visual_servo_combined.sh|visual_servo\" | grep -v grep || echo \"none\"; "
            'echo "--- ROS nodes ---"; '
            "ros2 node list 2>/dev/null || echo \"No ROS nodes found\"; "
            'echo "--- ROS topics with types ---"; '
            "ros2 topic list -t 2>/dev/null || echo \"No ROS topics found\"; "
            'echo "--- Joint-related topics discovered dynamically ---"; '
            "JOINT_TOPICS=$(ros2 topic list 2>/dev/null | grep -E \"joint|gripper\" || true); "
            'if [ -z \"$JOINT_TOPICS\" ]; then '
            'echo \"No joint topics found\"; '
            "else "
            'printf \"%s\n\" \"$JOINT_TOPICS\"; '
            'for TOPIC in $JOINT_TOPICS; do '
            'echo \"--- Topic info: $TOPIC ---\"; '
            'ros2 topic info \"$TOPIC\" 2>/dev/null || echo \"missing\"; '
            'echo \"--- Topic sample: $TOPIC ---\"; '
            'timeout 3s ros2 topic echo --once \"$TOPIC\" 2>/dev/null || echo \"no sample\"; '
            'done; '
            "fi; "
            f'echo "--- Robot State Publisher Log ---"; '
            f'tail -n 40 {self.robot_state_log_file} 2>/dev/null || echo "No robot state publisher log"; '
            "'"
        )
        self.run_ssh_command_async(cmd, "Debug LSL Status")

    def on_close(self):
        self._stop_robot_state_publisher_before_disconnect()
        self.ssh.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = FR3LauncherApp(root)
    root.mainloop()
