from collections import deque
from datetime import datetime
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageTk

from app.project_version import __version__
from bridge.interaction_event_client import InteractionEventClient
from recognition import holistic_tracker as core
from recognition.emotion_recognizer import EmotionRecognizer
from recognition.stt_engine import (
    LANGUAGE_OPTIONS,
    PROVIDER_OPTIONS,
    SENSITIVITY_OPTIONS,
    SILENCE_OPTIONS,
    RealtimeSTT,
)


DISPLAY_WIDTH = 960
DISPLAY_HEIGHT = 540
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMOTION_MODEL_PATH = PROJECT_ROOT / "models" / "epoch72_best_acc_0.8664.pth"
EMOTION_INFERENCE_INTERVAL_MS = 150
EMOTION_NEUTRAL_CONFIDENCE_THRESHOLD = 0.50
EMOTION_NEUTRAL_MARGIN_THRESHOLD = 0.15
AIR_DRAWING_COLORS = {
    "left": (0, 0, 255),
    "right": (255, 0, 0),
}


LABEL_CAMERA = "\uce74\uba54\ub77c"
LABEL_REFRESH = "\uce74\uba54\ub77c \uc0c8\ub85c\uace0\uce68"
LABEL_START = "\uc2dc\uc791"
LABEL_MODE = "\ubaa8\ub4dc"
LABEL_RPS = "\uac00\uc704\ubc14\uc704\ubcf4"
LABEL_CHAM = "\ucc38\ucc38\ucc38"
LABEL_AIR = "\uc5d0\uc5b4\ub4dc\ub85c\uc789"
LABEL_WAVE = "\uc190 \ud754\ub4e4\uae30"
LABEL_HAND_GESTURE = "\uc5c4\uc9c0\ucc99/\ud558\ud2b8/OK"
LABEL_HEAD_GESTURE = "\uace0\uac1c \ub044\ub355/\uc813\uae30"
LABEL_ATTENTION = "\uc751\uc2dc/\uc790\ub9ac\ube44\uc6c0"
LABEL_TOGGLES = "\ud1a0\uae00"
LABEL_TRACKING = "\ud2b8\ub798\ud0b9 \ud45c\uc2dc"
LABEL_MARKER_ONLY = "\uac80\uc740\ud654\uba74 \ub9c8\ucee4\ub9cc"
LABEL_MIRROR = "\uc88c\uc6b0 \ubc18\uc804"
LABEL_INFO_OVERLAY = "\uc88c\uce21 \uc0c1\ub2e8 \uc815\ubcf4"
LABEL_EMOTION = "\uac10\uc815 \uc778\uc2dd"
LABEL_STATUS = "\uc0c1\ud0dc"
LABEL_ALWAYS_RECOGNITION = "\uc0c1\uc2dc \uc778\uc2dd"
LABEL_STT = "STT"
LABEL_MIC = "\ub9c8\uc774\ud06c"
LABEL_STT_REFRESH = "\ub9c8\uc774\ud06c \uc0c8\ub85c\uace0\uce68"
LABEL_STT_START = "STT \uc2dc\uc791"
LABEL_STT_STOP = "STT \uc911\uc9c0"
LABEL_STT_SAVE = "STT \uc800\uc7a5"
LABEL_STT_CLEAR = "STT \uc9c0\uc6b0\uae30"
LABEL_STT_RESULT = "STT Result"

MODE_LABELS = {
    "rps": LABEL_RPS,
    "cham": LABEL_CHAM,
    "air": LABEL_AIR,
}


class HolisticGuiApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Holistic Tracking GUI v{__version__}")
        self.root.geometry("1420x860")
        self.root.configure(bg="#101418")

        self.capture_settings = SimpleNamespace(
            camera_backend="auto",
            camera_width=1280,
            camera_height=720,
        )

        self.cap = None
        self.capture_fps = 30.0
        self.pending_frame = None
        self.current_photo = None
        self.frame_index = 0
        self.camera_candidates = []
        self.active_mode = "rps"
        self.air_paths = {"left": [], "right": []}
        self.air_max_points = 180
        self.wave_histories = {"left": deque(maxlen=30), "right": deque(maxlen=30)}
        self.head_history = deque(maxlen=36)
        self.away_frame_count = 0
        self.emotion_result = None
        self.last_emotion_inference_ms = -EMOTION_INFERENCE_INTERVAL_MS
        self.always_results = {}
        self.mode_result = {"active": None, "result": None}
        self.latest_speech_text = ""
        self.last_sent_interaction_events = {}

        self.camera_var = tk.StringVar()
        self.source_var = tk.StringVar(
            value="\uce74\uba54\ub77c\ub97c \uc120\ud0dd\ud55c \ub4a4 \uc2dc\uc791\ud558\uc138\uc694."
        )
        self.mode_var = tk.StringVar(
            value="\ud604\uc7ac \ubaa8\ub4dc: " + LABEL_RPS
        )
        self.result_var = tk.StringVar(
            value="\uc778\uc2dd \uacb0\uacfc \ub300\uae30 \uc911"
        )
        self.status_var = tk.StringVar(
            value="\ub300\uae30 \uc911"
        )
        self.always_wave_status_var = tk.StringVar(value=f"{LABEL_WAVE}: -")
        self.always_gesture_status_var = tk.StringVar(value=f"{LABEL_HAND_GESTURE}: -")
        self.always_head_status_var = tk.StringVar(value=f"{LABEL_HEAD_GESTURE}: -")
        self.always_attention_status_var = tk.StringVar(value=f"{LABEL_ATTENTION}: -")
        self.stt_status_var = tk.StringVar(value="STT \ub300\uae30 \uc911")
        self.stt_mic_var = tk.StringVar()
        self.stt_provider_var = tk.StringVar(value="google")
        self.stt_silence_var = tk.StringVar(value="0.8 sec")
        self.stt_sensitivity_var = tk.StringVar(value="medium")
        self.stt_language_var = tk.StringVar(value="ko-KR")
        self.stt_timestamps_var = tk.BooleanVar(value=True)

        self.tracking_var = tk.BooleanVar(value=True)
        self.marker_only_var = tk.BooleanVar(value=False)
        self.mirror_var = tk.BooleanVar(value=False)
        self.info_overlay_var = tk.BooleanVar(value=True)
        self.emotion_var = tk.BooleanVar(value=False)
        self.always_recognition_var = tk.BooleanVar(value=True)
        self.stt = RealtimeSTT()

        self.holistic = core.mp_holistic.Holistic(
            static_image_mode=False,
            model_complexity=2,
            smooth_landmarks=True,
            enable_segmentation=False,
            refine_face_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.emotion_recognizer = None
        self.load_emotion_model()
        self.event_client = InteractionEventClient()
        self.event_client.start()

        self.build_ui()
        self.refresh_cameras()
        self.refresh_stt_microphones(show_error=False)
        self.show_placeholder(
            "\uce74\uba54\ub77c\ub97c \uc2dc\uc791\ud558\uba74 \uc778\uc2dd \ud654\uba74\uc774 \uc5ec\uae30\uc5d0 \ud45c\uc2dc\ub429\ub2c8\ub2e4."
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(0, self.update_frame)
        self.root.after(100, self.poll_stt_events)

    def build_ui(self):
        container = tk.Frame(self.root, bg="#101418")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        control_shell = tk.Frame(container, bg="#161c22", width=360)
        control_shell.pack(side="left", fill="y")
        control_shell.pack_propagate(False)

        control_canvas = tk.Canvas(
            control_shell,
            bg="#161c22",
            highlightthickness=0,
            bd=0,
        )
        control_scrollbar = tk.Scrollbar(
            control_shell,
            orient="vertical",
            command=control_canvas.yview,
        )
        control_panel = tk.Frame(control_canvas, bg="#161c22")
        control_window = control_canvas.create_window(
            (0, 0),
            window=control_panel,
            anchor="nw",
        )
        control_panel.bind(
            "<Configure>",
            lambda event: control_canvas.configure(scrollregion=control_canvas.bbox("all")),
        )
        control_canvas.bind(
            "<Configure>",
            lambda event: control_canvas.itemconfig(control_window, width=event.width),
        )
        control_canvas.configure(yscrollcommand=control_scrollbar.set)
        control_canvas.pack(side="left", fill="both", expand=True)
        control_scrollbar.pack(side="right", fill="y")

        video_panel = tk.Frame(container, bg="#0b0f13")
        video_panel.pack(side="right", fill="both", expand=True, padx=(16, 0))

        title = tk.Label(
            control_panel,
            text="Holistic Control",
            bg="#161c22",
            fg="#f4f7fb",
            font=("Malgun Gothic", 20, "bold"),
            anchor="w",
        )
        title.pack(fill="x", padx=18, pady=(18, 8))

        subtitle = tk.Label(
            control_panel,
            text=(
                "\uc5bc\uad74, \uc0c1\uccb4, \uc190 \ud2b8\ub798\ud0b9\uacfc "
                "\uc81c\uc2a4\ucc98 \ubaa8\ub4dc\ub97c \ud55c \ud654\uba74\uc5d0\uc11c \uc81c\uc5b4\ud569\ub2c8\ub2e4."
            ),
            bg="#161c22",
            fg="#b8c2cc",
            font=("Malgun Gothic", 10),
            justify="left",
            wraplength=290,
            anchor="w",
        )
        subtitle.pack(fill="x", padx=18, pady=(0, 18))

        self.add_section_label(control_panel, LABEL_CAMERA)

        self.camera_menu = tk.OptionMenu(control_panel, self.camera_var, "")
        self.camera_menu.config(
            bg="#1f2730",
            fg="#f4f7fb",
            activebackground="#27313d",
            activeforeground="#f4f7fb",
            highlightthickness=0,
            relief="flat",
            font=("Consolas", 10),
        )
        self.camera_menu["menu"].config(
            bg="#1f2730",
            fg="#f4f7fb",
            activebackground="#314051",
            activeforeground="#ffffff",
        )
        self.camera_menu.pack(fill="x", padx=18)

        camera_row = tk.Frame(control_panel, bg="#161c22")
        camera_row.pack(fill="x", padx=18, pady=(10, 18))

        tk.Button(
            camera_row,
            text=LABEL_REFRESH,
            command=self.refresh_cameras,
            bg="#24303d",
            fg="#f4f7fb",
            relief="flat",
            activebackground="#314051",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            camera_row,
            text=LABEL_START,
            command=self.start_selected_camera,
            bg="#2d6a4f",
            fg="#ffffff",
            relief="flat",
            activebackground="#3b8b66",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(10, 0))

        self.add_section_label(control_panel, LABEL_MODE)
        mode_grid = tk.Frame(control_panel, bg="#161c22")
        mode_grid.pack(fill="x", padx=18)
        mode_grid.columnconfigure(0, weight=1)
        mode_grid.columnconfigure(1, weight=1)

        self.mode_buttons = {}
        for index, (mode_key, label) in enumerate((
            ("rps", LABEL_RPS),
            ("cham", LABEL_CHAM),
            ("air", LABEL_AIR),
        )):
            button = tk.Button(
                mode_grid,
                text=label,
                command=lambda value=mode_key: self.set_mode(value),
                bg="#24303d",
                fg="#f4f7fb",
                relief="flat",
                activebackground="#314051",
                activeforeground="#ffffff",
                font=("Malgun Gothic", 10, "bold"),
                width=12,
                wraplength=132,
            )
            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0, 8 if index % 2 == 0 else 0),
                pady=(0, 8),
            )
            self.mode_buttons[mode_key] = button

        self.add_section_label(control_panel, LABEL_TOGGLES)
        toggle_frame = tk.Frame(control_panel, bg="#161c22")
        toggle_frame.pack(fill="x", padx=18)

        self.make_toggle(toggle_frame, LABEL_TRACKING, self.tracking_var).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_MARKER_ONLY, self.marker_only_var).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_MIRROR, self.mirror_var).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_INFO_OVERLAY, self.info_overlay_var).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_EMOTION, self.emotion_var).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_ALWAYS_RECOGNITION, self.always_recognition_var).pack(fill="x")

        self.add_section_label(control_panel, LABEL_STT)
        self.stt_mic_menu = tk.OptionMenu(control_panel, self.stt_mic_var, "")
        self.style_option_menu(self.stt_mic_menu)
        self.stt_mic_menu.pack(fill="x", padx=18, pady=(0, 8))

        stt_row = tk.Frame(control_panel, bg="#161c22")
        stt_row.pack(fill="x", padx=18, pady=(0, 8))
        tk.Button(
            stt_row,
            text=LABEL_STT_REFRESH,
            command=self.refresh_stt_microphones,
            bg="#24303d",
            fg="#f4f7fb",
            relief="flat",
            activebackground="#314051",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        ).pack(side="left", fill="x", expand=True)
        self.stt_start_button = tk.Button(
            stt_row,
            text=LABEL_STT_START,
            command=self.start_stt,
            bg="#2d6a4f",
            fg="#ffffff",
            relief="flat",
            activebackground="#3b8b66",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        )
        self.stt_start_button.pack(side="left", fill="x", expand=True, padx=(8, 0))

        stt_option_row = tk.Frame(control_panel, bg="#161c22")
        stt_option_row.pack(fill="x", padx=18, pady=(0, 8))
        self.make_small_option(stt_option_row, self.stt_provider_var, PROVIDER_OPTIONS).pack(side="left", fill="x", expand=True)
        self.make_small_option(stt_option_row, self.stt_language_var, LANGUAGE_OPTIONS).pack(side="left", fill="x", expand=True, padx=(8, 0))

        stt_turn_row = tk.Frame(control_panel, bg="#161c22")
        stt_turn_row.pack(fill="x", padx=18, pady=(0, 8))
        self.make_small_option(stt_turn_row, self.stt_sensitivity_var, SENSITIVITY_OPTIONS).pack(side="left", fill="x", expand=True)
        self.make_small_option(stt_turn_row, self.stt_silence_var, SILENCE_OPTIONS).pack(side="left", fill="x", expand=True, padx=(8, 0))

        stt_action_row = tk.Frame(control_panel, bg="#161c22")
        stt_action_row.pack(fill="x", padx=18, pady=(0, 8))
        self.stt_stop_button = tk.Button(
            stt_action_row,
            text=LABEL_STT_STOP,
            command=self.stop_stt,
            bg="#69353d",
            fg="#ffffff",
            relief="flat",
            activebackground="#7d414b",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
            state="disabled",
        )
        self.stt_stop_button.pack(side="left", fill="x", expand=True)
        tk.Button(
            stt_action_row,
            text=LABEL_STT_SAVE,
            command=self.save_stt_text,
            bg="#24303d",
            fg="#f4f7fb",
            relief="flat",
            activebackground="#314051",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Button(
            stt_action_row,
            text=LABEL_STT_CLEAR,
            command=self.clear_stt_text,
            bg="#24303d",
            fg="#f4f7fb",
            relief="flat",
            activebackground="#314051",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.make_toggle(control_panel, "\ud0c0\uc784\uc2a4\ud0ec\ud504 \ud45c\uc2dc", self.stt_timestamps_var).pack(fill="x", padx=18, pady=(0, 8))
        self.make_info_label(control_panel, self.stt_status_var).pack(fill="x", padx=18, pady=(0, 10))

        self.add_section_label(control_panel, LABEL_STATUS)
        self.make_info_label(control_panel, self.source_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.mode_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.result_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.always_wave_status_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.always_gesture_status_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.always_head_status_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.always_attention_status_var).pack(fill="x", padx=18, pady=(0, 10))
        self.make_info_label(control_panel, self.status_var).pack(fill="x", padx=18)

        video_title = tk.Label(
            video_panel,
            text="Recognition Screen",
            bg="#0b0f13",
            fg="#f4f7fb",
            font=("Malgun Gothic", 18, "bold"),
            anchor="w",
        )
        video_title.pack(fill="x", pady=(0, 12))

        self.video_label = tk.Label(
            video_panel,
            bg="#05080c",
            bd=0,
        )
        self.video_label.pack(fill="both", expand=True)

        stt_output_panel = tk.Frame(video_panel, bg="#0b0f13", height=170)
        stt_output_panel.pack(fill="x", pady=(12, 0))
        stt_output_panel.pack_propagate(False)

        tk.Label(
            stt_output_panel,
            text=LABEL_STT_RESULT,
            bg="#0b0f13",
            fg="#f4f7fb",
            font=("Malgun Gothic", 12, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        text_shell = tk.Frame(stt_output_panel, bg="#05080c")
        text_shell.pack(fill="both", expand=True)
        self.stt_output = tk.Text(
            text_shell,
            bg="#05080c",
            fg="#eaf6ff",
            insertbackground="#f4f7fb",
            selectbackground="#284761",
            relief="flat",
            wrap="word",
            font=("Consolas", 11),
            padx=12,
            pady=10,
            height=5,
        )
        self.stt_output.pack(side="left", fill="both", expand=True)
        stt_scrollbar = tk.Scrollbar(text_shell, command=self.stt_output.yview)
        stt_scrollbar.pack(side="right", fill="y")
        self.stt_output.configure(yscrollcommand=stt_scrollbar.set)
        self.append_stt_text("STT ready.\n")

        self.update_mode_buttons()

    def add_section_label(self, parent, text):
        label = tk.Label(
            parent,
            text=text,
            bg="#161c22",
            fg="#7fd1b9",
            font=("Malgun Gothic", 11, "bold"),
            anchor="w",
        )
        label.pack(fill="x", padx=18, pady=(0, 8))

    def make_toggle(self, parent, text, variable):
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg="#161c22",
            fg="#f4f7fb",
            selectcolor="#24303d",
            activebackground="#161c22",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 10),
            anchor="w",
            relief="flat",
            highlightthickness=0,
        )

    def style_option_menu(self, option_menu):
        option_menu.config(
            bg="#1f2730",
            fg="#f4f7fb",
            activebackground="#27313d",
            activeforeground="#f4f7fb",
            highlightthickness=0,
            relief="flat",
            font=("Consolas", 9),
        )
        option_menu["menu"].config(
            bg="#1f2730",
            fg="#f4f7fb",
            activebackground="#314051",
            activeforeground="#ffffff",
        )

    def make_small_option(self, parent, variable, values):
        option = tk.OptionMenu(parent, variable, *values)
        self.style_option_menu(option)
        option.config(font=("Consolas", 8))
        return option

    def make_info_label(self, parent, variable):
        return tk.Label(
            parent,
            textvariable=variable,
            bg="#1b232c",
            fg="#d6dde5",
            font=("Malgun Gothic", 10),
            justify="left",
            wraplength=290,
            anchor="w",
            padx=12,
            pady=10,
        )

    def show_placeholder(self, text):
        frame = np.zeros((DISPLAY_HEIGHT, DISPLAY_WIDTH, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "Holistic Preview",
            (70, 220),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (240, 245, 250),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            text,
            (70, 290),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (180, 190, 200),
            2,
            cv2.LINE_AA,
        )
        self.render_frame(frame)

    def refresh_cameras(self):
        self.camera_candidates = core.discover_webcams(self.capture_settings)
        menu = self.camera_menu["menu"]
        menu.delete(0, "end")

        if not self.camera_candidates:
            label = "\uc0ac\uc6a9 \uac00\ub2a5\ud55c \uc6f9\ucea0 \uc5c6\uc74c"
            self.camera_var.set(label)
            menu.add_command(label=label, command=lambda value=label: self.camera_var.set(value))
            self.status_var.set("\uc6f9\ucea0\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")
            return

        for candidate in self.camera_candidates:
            label = f"index {candidate['index']} / {candidate['backend_label']}"
            menu.add_command(label=label, command=lambda value=label: self.camera_var.set(value))

        default_label = f"index {self.camera_candidates[0]['index']} / {self.camera_candidates[0]['backend_label']}"
        self.camera_var.set(default_label)
        self.status_var.set(f"\uc6f9\ucea0 {len(self.camera_candidates)}\uac1c \uac10\uc9c0")

    def refresh_stt_microphones(self, show_error=True):
        menu = self.stt_mic_menu["menu"]
        menu.delete(0, "end")

        try:
            labels = self.stt.refresh_microphones()
        except Exception as exc:
            label = "\ub9c8\uc774\ud06c \uc0ac\uc6a9 \ubd88\uac00"
            self.stt_mic_var.set(label)
            menu.add_command(label=label, command=lambda value=label: self.stt_mic_var.set(value))
            self.stt_status_var.set(f"STT \uc900\ube44 \uc2e4\ud328: {exc}")
            if show_error:
                messagebox.showerror("STT", str(exc))
            return

        if not labels:
            label = "\uc0ac\uc6a9 \uac00\ub2a5\ud55c \ub9c8\uc774\ud06c \uc5c6\uc74c"
            self.stt_mic_var.set(label)
            menu.add_command(label=label, command=lambda value=label: self.stt_mic_var.set(value))
            self.stt_status_var.set("STT: \ub9c8\uc774\ud06c\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")
            return

        for label in labels:
            menu.add_command(label=label, command=lambda value=label: self.stt_mic_var.set(value))
        if self.stt_mic_var.get() not in labels:
            self.stt_mic_var.set(labels[0])
        self.stt_status_var.set(f"STT: \ub9c8\uc774\ud06c {len(labels)}\uac1c \uac10\uc9c0")

    def start_stt(self):
        try:
            self.stt.start(
                self.stt_mic_var.get(),
                self.stt_provider_var.get(),
                self.stt_silence_var.get(),
                self.stt_sensitivity_var.get(),
                self.stt_language_var.get(),
                self.stt_timestamps_var.get(),
            )
        except Exception as exc:
            self.stt_status_var.set(f"STT \uc2dc\uc791 \uc2e4\ud328: {exc}")
            messagebox.showerror("STT", str(exc))
            return

        self.stt_start_button.configure(state="disabled")
        self.stt_stop_button.configure(state="normal")
        self.stt_status_var.set("STT: Google Web Speech \uc900\ube44 \uc911")

    def stop_stt(self):
        self.stt.stop()
        self.stt_stop_button.configure(state="disabled")
        self.stt_status_var.set("STT: \uc911\uc9c0 \uc911")

    def poll_stt_events(self):
        for kind, value in self.stt.drain_events():
            if kind == "text":
                self.append_stt_text(value)
            elif kind == "speech":
                self.latest_speech_text = value
            elif kind == "status":
                self.stt_status_var.set(value)
            elif kind == "error":
                self.append_stt_text(f"\n[STT error] {value}\n")
                self.stt_status_var.set(f"STT error: {value}")
                messagebox.showerror("STT", value)
            elif kind == "running" and value == "false":
                self.stt_start_button.configure(state="normal")
                self.stt_stop_button.configure(state="disabled")
        self.root.after(100, self.poll_stt_events)

    def append_stt_text(self, text):
        self.stt_output.insert("end", text)
        self.stt_output.see("end")

    def clear_stt_text(self):
        self.stt_output.delete("1.0", "end")

    def save_stt_text(self):
        text = self.stt_output.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("STT", "\uc800\uc7a5\ud560 STT \ud14d\uc2a4\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
            return

        default_name = f"stt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = filedialog.asksaveasfilename(
            title="STT \ud14d\uc2a4\ud2b8 \uc800\uc7a5",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not path:
            return
        Path(path).write_text(text, encoding="utf-8")
        self.stt_status_var.set(f"STT \uc800\uc7a5 \uc644\ub8cc: {Path(path).name}")

    def load_emotion_model(self):
        try:
            self.emotion_recognizer = EmotionRecognizer(EMOTION_MODEL_PATH)
        except Exception as exc:
            self.emotion_recognizer = None
            self.status_var.set(f"\uac10\uc815 \ubaa8\ub378 \ub85c\ub4dc \uc2e4\ud328: {exc}")

    def start_selected_camera(self):
        if not self.camera_candidates:
            self.refresh_cameras()
            if not self.camera_candidates:
                return

        selected_label = self.camera_var.get()
        selected_candidate = self.camera_candidates[0]
        for candidate in self.camera_candidates:
            candidate_label = f"index {candidate['index']} / {candidate['backend_label']}"
            if candidate_label == selected_label:
                selected_candidate = candidate
                break

        self.release_camera()
        result = core.try_open_webcam(
            selected_candidate["index"],
            selected_candidate["backend"],
            selected_candidate["backend_label"],
            self.capture_settings.camera_width,
            self.capture_settings.camera_height,
        )

        if result is None:
            self.status_var.set("\uc120\ud0dd\ud55c \uce74\uba54\ub77c\ub97c \uc5f4\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")
            return

        self.cap = result["cap"]
        self.pending_frame = result["frame"]
        self.capture_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        if self.capture_fps <= 0:
            self.capture_fps = 30.0
        self.frame_index = 0
        self.clear_air_paths()
        self.reset_motion_states()
        self.source_var.set(
            f"\uc18c\uc2a4: webcam index {selected_candidate['index']} via {selected_candidate['backend_label']}"
        )
        self.status_var.set("\uce74\uba54\ub77c \uc2e4\ud589 \uc911")

    def set_mode(self, mode_key):
        if self.active_mode == mode_key:
            self.active_mode = None
        else:
            self.active_mode = mode_key

        self.clear_air_paths()
        self.reset_motion_states()
        self.update_mode_buttons()
        if self.active_mode in MODE_LABELS:
            self.mode_var.set("\ud604\uc7ac \ubaa8\ub4dc: " + MODE_LABELS[self.active_mode])
            self.result_var.set("\uc778\uc2dd \uacb0\uacfc \ub300\uae30 \uc911")
        else:
            self.mode_var.set("\ud604\uc7ac \ubaa8\ub4dc: \uc5c6\uc74c")
            self.result_var.set("\ubaa8\ub4dc \uaebc\uc9d0")

    def update_mode_buttons(self):
        for mode_key, button in self.mode_buttons.items():
            if mode_key == self.active_mode:
                button.configure(bg="#7fd1b9", fg="#0d141a")
            else:
                button.configure(bg="#24303d", fg="#f4f7fb")

    def clear_air_paths(self):
        self.air_paths = {"left": [], "right": []}

    def reset_motion_states(self):
        self.wave_histories = {"left": deque(maxlen=30), "right": deque(maxlen=30)}
        self.head_history = deque(maxlen=36)
        self.away_frame_count = 0

    def release_camera(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.pending_frame = None

    def update_frame(self):
        if self.cap is None:
            self.root.after(30, self.update_frame)
            return

        if self.pending_frame is not None:
            has_frame = True
            frame_bgr = self.pending_frame
            self.pending_frame = None
        else:
            has_frame, frame_bgr = self.cap.read()

        if not has_frame or frame_bgr is None:
            self.status_var.set("\ud504\ub808\uc784\uc744 \uc77d\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")
            self.release_camera()
            self.root.after(30, self.update_frame)
            return

        if self.mirror_var.get():
            frame_bgr = cv2.flip(frame_bgr, 1)

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        results = self.holistic.process(frame_rgb)
        frame_rgb.flags.writeable = True

        height, width = frame_bgr.shape[:2]
        timestamp_ms = int((self.frame_index / self.capture_fps) * 1000)
        tracking_enabled = self.tracking_var.get()
        rps_enabled = self.active_mode == "rps"

        frame_record = core.build_frame_record(
            self.frame_index,
            timestamp_ms,
            width,
            height,
            results,
            tracking_enabled,
            rps_enabled,
        )
        self.update_emotion_result(frame_bgr, frame_record, timestamp_ms)
        self.update_always_recognition(frame_record, width)

        if self.marker_only_var.get():
            base_frame = np.zeros_like(frame_bgr)
        else:
            base_frame = frame_bgr

        annotated = core.annotate_frame(
            base_frame,
            frame_record,
            results,
            tracking_enabled,
            rps_enabled,
            draw_labels=False,
            show_info_overlay=self.info_overlay_var.get(),
            hand_label_side_map=self.get_hand_label_side_map(),
        )

        self.apply_always_recognition_overlay(annotated)
        self.apply_mode_overlay(annotated, frame_record)
        self.apply_emotion_overlay(annotated)
        self.send_recognition_state()
        self.render_frame(annotated)

        self.frame_index += 1
        self.root.after(15, self.update_frame)

    def apply_mode_overlay(self, frame_bgr, frame_record):
        self.mode_result = {"active": self.active_mode, "result": None}
        if self.active_mode == "rps":
            self.apply_rps_overlay(frame_bgr, frame_record)
        elif self.active_mode == "cham":
            self.apply_cham_overlay(frame_bgr, frame_record)
        elif self.active_mode == "air":
            self.apply_air_overlay(frame_bgr, frame_record)
        elif self.active_mode == "wave":
            self.apply_wave_overlay(frame_bgr, frame_record)
        elif self.active_mode == "gesture":
            self.apply_gesture_overlay(frame_bgr, frame_record)
        elif self.active_mode == "head":
            self.apply_head_overlay(frame_bgr, frame_record)
        elif self.active_mode == "attention":
            self.apply_attention_overlay(frame_bgr, frame_record)
        else:
            self.mode_result = {"active": None, "result": None}
            self.result_var.set("\ubaa8\ub4dc \uaebc\uc9d0")

    def update_always_recognition(self, frame_record, frame_width):
        self.always_results = {}

        wave_states = self.update_wave_state(frame_record, frame_width)
        left_state, right_state = self.get_display_side_values(wave_states)
        self.always_results["wave"] = {
            "states": wave_states,
            "left_state": left_state,
            "right_state": right_state,
        }

        gesture_states = self.update_gesture_state(frame_record)
        left_state, right_state = self.get_display_side_values(gesture_states)
        self.always_results["gesture"] = {
            "states": gesture_states,
            "left_state": left_state,
            "right_state": right_state,
        }

        head_state, result_state, overlay_state = self.update_head_state(frame_record)
        self.always_results["head"] = {
            "state": head_state,
            "result_state": result_state,
            "overlay_state": overlay_state,
        }

        attention_state, result_state, overlay_state = self.update_attention_state(frame_record)
        self.always_results["attention"] = {
            "state": attention_state,
            "result_state": result_state,
            "overlay_state": overlay_state,
        }
        self.update_always_status_labels()

    def update_always_status_labels(self):
        if not self.always_recognition_var.get():
            self.always_wave_status_var.set(f"{LABEL_WAVE}: \uc228\uae40")
            self.always_gesture_status_var.set(f"{LABEL_HAND_GESTURE}: \uc228\uae40")
            self.always_head_status_var.set(f"{LABEL_HEAD_GESTURE}: \uc228\uae40")
            self.always_attention_status_var.set(f"{LABEL_ATTENTION}: \uc228\uae40")
            return

        wave = self.always_results.get("wave", {})
        gesture = self.always_results.get("gesture", {})
        head = self.always_results.get("head", {})
        attention = self.always_results.get("attention", {})
        self.always_wave_status_var.set(
            f"{LABEL_WAVE}: L={wave.get('left_state', '-')} R={wave.get('right_state', '-')}"
        )
        self.always_gesture_status_var.set(
            f"{LABEL_HAND_GESTURE}: L={gesture.get('left_state', '-')} R={gesture.get('right_state', '-')}"
        )
        self.always_head_status_var.set(f"{LABEL_HEAD_GESTURE}: {head.get('result_state', '-')}")
        self.always_attention_status_var.set(
            f"{LABEL_ATTENTION}: {attention.get('result_state', '-')}"
        )

    def send_interaction_event_if_changed(self, key, event):
        signature = json.dumps(event, ensure_ascii=False, sort_keys=True)
        if self.last_sent_interaction_events.get(key) == signature:
            return
        self.last_sent_interaction_events[key] = signature
        self.send_interaction_event(key, event)

    def send_interaction_event(self, key, event):
        self.event_client.send(event)

    def send_recognition_state(self):
        event = self.build_recognition_state_event()
        self.send_interaction_event_if_changed("recognition_state", event)

    def build_recognition_state_event(self):
        wave = self.always_results.get("wave", {})
        gesture = self.always_results.get("gesture", {})
        head = self.always_results.get("head", {})
        attention = self.always_results.get("attention", {})
        return {
            "type": "recognition_state",
            "always": {
                "wave": {
                    "left": wave.get("left_state"),
                    "right": wave.get("right_state"),
                    "raw": wave.get("states", {}),
                },
                "hand_gesture": {
                    "left": gesture.get("left_state"),
                    "right": gesture.get("right_state"),
                    "raw": gesture.get("states", {}),
                },
                "head": {
                    "value": head.get("state"),
                    "label": head.get("result_state"),
                    "overlay": head.get("overlay_state"),
                },
                "attention": {
                    "value": attention.get("state"),
                    "label": attention.get("result_state"),
                    "overlay": attention.get("overlay_state"),
                },
                "emotion": self.build_emotion_state(),
            },
            "mode": self.mode_result,
            "speech": {
                "latest_text": self.latest_speech_text,
            },
        }

    def build_emotion_state(self):
        if self.emotion_result is None:
            return {
                "label": None,
                "scores": {},
            }
        return {
            "label": self.emotion_result["label"],
            "scores": self.emotion_result["scores"],
        }

    def apply_always_recognition_overlay(self, frame_bgr):
        if not self.always_recognition_var.get() or not self.always_results:
            return

        wave = self.always_results.get("wave", {})
        gesture = self.always_results.get("gesture", {})
        head = self.always_results.get("head", {})
        attention = self.always_results.get("attention", {})
        lines = [
            "Always Recognition",
            f"Wave: L={wave.get('left_state', '-')} R={wave.get('right_state', '-')}",
            f"Gesture: L={gesture.get('left_state', '-')} R={gesture.get('right_state', '-')}",
            f"Head: {head.get('overlay_state', '-')}",
            f"Attention: {attention.get('overlay_state', '-')}",
        ]

        box_width = 430
        line_height = 28
        box_height = 24 + (len(lines) * line_height)
        x1 = 20
        y1 = max(20, frame_bgr.shape[0] - box_height - 72)
        x2 = x1 + box_width
        y2 = y1 + box_height

        overlay = frame_bgr.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (15, 20, 26), -1)
        cv2.addWeighted(overlay, 0.72, frame_bgr, 0.28, 0, frame_bgr)
        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (127, 209, 185), 2)

        for index, line in enumerate(lines):
            color = (127, 209, 185) if index == 0 else (240, 245, 250)
            scale = 0.68 if index == 0 else 0.58
            thickness = 2 if index == 0 else 1
            cv2.putText(
                frame_bgr,
                line,
                (x1 + 14, y1 + 30 + (index * line_height)),
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                color,
                thickness,
                cv2.LINE_AA,
            )

    def update_emotion_result(self, frame_bgr, frame_record, timestamp_ms):
        if self.emotion_recognizer is None:
            self.emotion_result = None
            return

        if timestamp_ms - self.last_emotion_inference_ms < EMOTION_INFERENCE_INTERVAL_MS:
            return

        self.last_emotion_inference_ms = timestamp_ms

        face_crop = self.extract_face_crop(frame_bgr, frame_record)
        if face_crop is None:
            self.emotion_result = None
            return

        try:
            prediction = self.emotion_recognizer.predict(face_crop)
        except Exception:
            self.emotion_result = None
            return

        scores = prediction["scores"]
        label = self.get_emotion_display_label(scores)
        self.emotion_result = {
            "label": label,
            "confidence": scores.get(label, 0.0),
            "scores": scores,
        }

    def get_emotion_display_label(self, scores):
        ranked_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not ranked_scores:
            return "Neutral"

        top_label, top_score = ranked_scores[0]
        second_score = ranked_scores[1][1] if len(ranked_scores) > 1 else 0.0
        if top_score < EMOTION_NEUTRAL_CONFIDENCE_THRESHOLD:
            return "Neutral"
        if top_score - second_score < EMOTION_NEUTRAL_MARGIN_THRESHOLD:
            return "Neutral"
        return top_label

    def extract_face_crop(self, frame_bgr, frame_record):
        face_landmarks = frame_record["face_landmarks"]
        if not face_landmarks:
            return None

        height, width = frame_bgr.shape[:2]
        xs = [point["pixel_x"] for point in face_landmarks]
        ys = [point["pixel_y"] for point in face_landmarks]
        if not xs or not ys:
            return None

        x1, x2 = max(0, min(xs)), min(width, max(xs))
        y1, y2 = max(0, min(ys)), min(height, max(ys))

        box_width = x2 - x1
        box_height = y2 - y1
        if box_width <= 0 or box_height <= 0:
            return None

        pad_x = int(box_width * 0.18)
        pad_y = int(box_height * 0.22)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(width, x2 + pad_x)
        y2 = min(height, y2 + pad_y)

        if x2 <= x1 or y2 <= y1:
            return None

        return frame_bgr[y1:y2, x1:x2]

    def apply_emotion_overlay(self, frame_bgr):
        if not self.emotion_var.get():
            return

        if self.emotion_recognizer is None:
            text = "Emotion: MODEL ERROR"
            score_lines = []
        elif self.emotion_result is None:
            text = "Emotion: NONE"
            score_lines = []
        else:
            label = self.emotion_result["label"]
            text = f"Emotion: {label}"
            score_lines = [
                f"{score_label}: {score * 100.0:.1f}%"
                for score_label, score in sorted(
                    self.emotion_result["scores"].items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ]

        box_width = 340
        box_height = 58 + (len(score_lines) * 28)
        x1 = frame_bgr.shape[1] - box_width - 20
        y1 = 20
        x2 = frame_bgr.shape[1] - 20
        y2 = y1 + box_height

        overlay = frame_bgr.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (15, 20, 26), -1)
        cv2.addWeighted(overlay, 0.72, frame_bgr, 0.28, 0, frame_bgr)
        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (127, 209, 185), 2)
        cv2.putText(
            frame_bgr,
            text,
            (x1 + 14, y1 + 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        for index, line in enumerate(score_lines):
            cv2.putText(
                frame_bgr,
                line,
                (x1 + 14, y1 + 58 + (index * 28)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                (210, 226, 235),
                2,
                cv2.LINE_AA,
            )

    def apply_rps_overlay(self, frame_bgr, frame_record):
        left_state, right_state = self.get_display_hand_states(frame_record)
        self.result_var.set(f"{LABEL_RPS}: L={left_state}, R={right_state}")
        self.mode_result = {
            "active": "rps",
            "result": {
                "left": left_state,
                "right": right_state,
            },
        }
        text = f"RPS  L:{left_state}  R:{right_state}"

        cv2.putText(
            frame_bgr,
            text,
            (40, frame_bgr.shape[0] - 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    def apply_cham_overlay(self, frame_bgr, frame_record):
        direction = self.detect_face_direction(frame_record["upper_body_landmarks"])
        self.result_var.set(f"{LABEL_CHAM}: {direction}")
        self.mode_result = {
            "active": "cham",
            "result": {
                "direction": direction,
            },
        }
        cv2.putText(
            frame_bgr,
            f"Cham Cham Cham: {direction}",
            (40, frame_bgr.shape[0] - 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    def apply_air_overlay(self, frame_bgr, frame_record):
        self.update_air_paths(frame_record)
        self.draw_air_paths(frame_bgr)
        self.result_var.set("\uc5d0\uc5b4\ub4dc\ub85c\uc789: \uc190\uac00\ub77d \uacbd\ub85c \ud45c\uc2dc \uc911")
        self.mode_result = {
            "active": "air",
            "result": {
                "active": True,
                "left_points": len([point for point in self.air_paths["left"] if point is not None]),
                "right_points": len([point for point in self.air_paths["right"] if point is not None]),
            },
        }
        self.draw_mode_text(frame_bgr, "Air Drawing Active")

    def apply_wave_overlay(self, frame_bgr, frame_record):
        cached = self.always_results.get("wave")
        if cached is None:
            cached = {}
            wave_states = self.update_wave_state(frame_record, frame_bgr.shape[1])
            cached["states"] = wave_states
            cached["left_state"], cached["right_state"] = self.get_display_side_values(wave_states)

        wave_states = cached["states"]
        left_state = cached["left_state"]
        right_state = cached["right_state"]
        result_text = f"{LABEL_WAVE}: L={left_state}, R={right_state}"
        self.result_var.set(result_text)
        self.draw_hand_state_labels(frame_bgr, frame_record, wave_states)
        self.draw_mode_text(frame_bgr, f"Wave  L:{left_state}  R:{right_state}")

    def update_wave_state(self, frame_record, frame_width):
        self.update_wave_histories(frame_record)
        return {
            side: self.detect_wave(side, frame_width)
            for side in ("left", "right")
        }

    def apply_gesture_overlay(self, frame_bgr, frame_record):
        cached = self.always_results.get("gesture")
        if cached is None:
            cached = {}
            gesture_states = self.update_gesture_state(frame_record)
            cached["states"] = gesture_states
            cached["left_state"], cached["right_state"] = self.get_display_side_values(gesture_states)

        gesture_states = cached["states"]
        left_state = cached["left_state"]
        right_state = cached["right_state"]
        self.result_var.set(f"{LABEL_HAND_GESTURE}: L={left_state}, R={right_state}")
        self.draw_hand_state_labels(frame_bgr, frame_record, gesture_states)
        self.draw_mode_text(frame_bgr, f"Gesture  L:{left_state}  R:{right_state}")

    def update_gesture_state(self, frame_record):
        gesture_states = {
            "left": self.detect_static_hand_gesture(frame_record["left_hand_landmarks"]),
            "right": self.detect_static_hand_gesture(frame_record["right_hand_landmarks"]),
        }
        if self.detect_two_hand_heart(frame_record):
            gesture_states["left"] = "HEART"
            gesture_states["right"] = "HEART"

        return gesture_states

    def apply_head_overlay(self, frame_bgr, frame_record):
        cached = self.always_results.get("head")
        if cached is None:
            head_state, result_state, overlay_state = self.update_head_state(frame_record)
        else:
            head_state = cached["state"]
            result_state = cached["result_state"]
            overlay_state = cached["overlay_state"]

        self.result_var.set(f"{LABEL_HEAD_GESTURE}: {result_state}")
        self.draw_mode_text(frame_bgr, f"Head Motion: {overlay_state}")

    def update_head_state(self, frame_record):
        self.update_head_history(frame_record)
        head_state = self.detect_head_motion()
        if head_state == "AGREE":
            result_state = "\ub3d9\uc758"
            overlay_state = "AGREE"
        elif head_state == "NEGATIVE":
            result_state = "\ubd80\uc815"
            overlay_state = "NEGATIVE"
        else:
            result_state = "\uc778\uc2dd \ub300\uae30"
            overlay_state = "WAITING"

        return head_state, result_state, overlay_state

    def apply_attention_overlay(self, frame_bgr, frame_record):
        cached = self.always_results.get("attention")
        if cached is None:
            attention_state, result_state, overlay_state = self.update_attention_state(frame_record)
        else:
            attention_state = cached["state"]
            result_state = cached["result_state"]
            overlay_state = cached["overlay_state"]

        self.result_var.set(f"{LABEL_ATTENTION}: {result_state}")
        self.draw_mode_text(frame_bgr, f"Attention: {overlay_state}")

    def update_attention_state(self, frame_record):
        attention_state = self.detect_attention_state(frame_record)
        if attention_state == "SCREEN":
            result_state = "\ud654\uba74 \uc751\uc2dc"
            overlay_state = "LOOKING AT SCREEN"
        elif attention_state == "LOOKING_AWAY":
            result_state = "\ud654\uba74 \ubc16 \uc751\uc2dc"
            overlay_state = "LOOKING AWAY"
        elif attention_state == "AWAY":
            result_state = "\uc790\ub9ac \ube44\uc6c0"
            overlay_state = "AWAY"
        else:
            result_state = "\uc5bc\uad74 \ucc3e\ub294 \uc911"
            overlay_state = "SEARCHING FACE"

        return attention_state, result_state, overlay_state

    def draw_mode_text(self, frame_bgr, text, color=(255, 255, 255)):
        cv2.putText(
            frame_bgr,
            text,
            (40, frame_bgr.shape[0] - 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            color,
            2,
            cv2.LINE_AA,
        )

    def draw_hand_state_labels(self, frame_bgr, frame_record, side_states):
        for side, state in side_states.items():
            records = frame_record[f"{side}_hand_landmarks"]
            anchor = core.hand_anchor_point(records)
            if anchor is None:
                continue
            display_side = self.get_display_side_name(side)
            cv2.putText(
                frame_bgr,
                f"{display_side.title()}: {state}",
                (anchor[0] + 10, max(30, anchor[1] - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (127, 209, 185),
                2,
                cv2.LINE_AA,
            )

    def get_display_side_values(self, side_values):
        if self.mirror_var.get():
            return side_values["right"], side_values["left"]
        return side_values["left"], side_values["right"]

    def get_display_side_name(self, side):
        if not self.mirror_var.get():
            return side
        return "right" if side == "left" else "left"

    def update_wave_histories(self, frame_record):
        for side in ("left", "right"):
            anchor = core.hand_anchor_point(frame_record[f"{side}_hand_landmarks"])
            self.wave_histories[side].append(anchor)

    def detect_wave(self, side, frame_width):
        points = [point for point in self.wave_histories[side] if point is not None]
        if len(points) < 12:
            return "WAIT"

        xs = [point[0] for point in points]
        amplitude = max(xs) - min(xs)
        min_amplitude = max(42, frame_width * 0.055)
        direction_changes = self.count_direction_changes(xs, min_delta=8)
        if amplitude >= min_amplitude and direction_changes >= 2:
            return "HELLO"
        return "NONE"

    def detect_static_hand_gesture(self, hand_records):
        pose = self.analyze_hand_pose(hand_records)
        if pose is None:
            return "NONE"

        extended = pose["extended"]
        folded_fingers = not any(
            extended[finger] for finger in ("index", "middle", "ring", "pinky")
        )
        if pose["thumb_up"] and folded_fingers:
            return "THUMBS_UP"
        if pose["pinch"] and extended["middle"] and extended["ring"] and extended["pinky"]:
            return "OK"
        if pose["pinch"] and not extended["middle"] and not extended["ring"] and not extended["pinky"]:
            return "HEART"
        return "NONE"

    def detect_two_hand_heart(self, frame_record):
        left_map = core.records_by_name(frame_record["left_hand_landmarks"])
        right_map = core.records_by_name(frame_record["right_hand_landmarks"])
        if not left_map or not right_map:
            return False

        left_scale = self.hand_scale(left_map)
        right_scale = self.hand_scale(right_map)
        scale = max(40, (left_scale + right_scale) / 2)
        threshold = scale * 0.75

        left_thumb = core.point_from_record(left_map.get("THUMB_TIP"))
        right_thumb = core.point_from_record(right_map.get("THUMB_TIP"))
        left_index = core.point_from_record(left_map.get("INDEX_FINGER_TIP"))
        right_index = core.point_from_record(right_map.get("INDEX_FINGER_TIP"))
        left_wrist = core.point_from_record(left_map.get("WRIST"))
        right_wrist = core.point_from_record(right_map.get("WRIST"))

        thumb_distance = core.distance_between_points(left_thumb, right_thumb)
        index_distance = core.distance_between_points(left_index, right_index)
        wrist_distance = core.distance_between_points(left_wrist, right_wrist)
        if thumb_distance is None or index_distance is None or wrist_distance is None:
            return False
        return thumb_distance < threshold and index_distance < threshold and wrist_distance > scale

    def analyze_hand_pose(self, hand_records):
        if not hand_records:
            return None

        hand_map = core.records_by_name(hand_records)
        scale = self.hand_scale(hand_map)
        thumb_tip = core.point_from_record(hand_map.get("THUMB_TIP"))
        thumb_ip = core.point_from_record(hand_map.get("THUMB_IP"))
        thumb_mcp = core.point_from_record(hand_map.get("THUMB_MCP"))
        wrist = core.point_from_record(hand_map.get("WRIST"))
        index_tip = core.point_from_record(hand_map.get("INDEX_FINGER_TIP"))

        thumb_angle = core.angle_between_points(thumb_mcp, thumb_ip, thumb_tip)
        thumb_up = (
            thumb_tip is not None
            and thumb_ip is not None
            and thumb_mcp is not None
            and wrist is not None
            and thumb_angle is not None
            and thumb_angle >= 145
            and thumb_tip[1] < thumb_ip[1] < thumb_mcp[1]
            and wrist[1] - thumb_tip[1] > scale * 0.28
        )

        pinch_distance = core.distance_between_points(thumb_tip, index_tip)
        pinch = pinch_distance is not None and pinch_distance <= scale * 0.42

        extended = {
            "thumb": thumb_up,
            "index": core.finger_is_extended(
                hand_map,
                "INDEX_FINGER_MCP",
                "INDEX_FINGER_PIP",
                "INDEX_FINGER_TIP",
            ),
            "middle": core.finger_is_extended(
                hand_map,
                "MIDDLE_FINGER_MCP",
                "MIDDLE_FINGER_PIP",
                "MIDDLE_FINGER_TIP",
            ),
            "ring": core.finger_is_extended(
                hand_map,
                "RING_FINGER_MCP",
                "RING_FINGER_PIP",
                "RING_FINGER_TIP",
            ),
            "pinky": core.finger_is_extended(
                hand_map,
                "PINKY_MCP",
                "PINKY_PIP",
                "PINKY_TIP",
            ),
        }

        return {
            "extended": extended,
            "pinch": pinch,
            "thumb_up": thumb_up,
        }

    def hand_scale(self, hand_map):
        wrist = core.point_from_record(hand_map.get("WRIST"))
        middle_mcp = core.point_from_record(hand_map.get("MIDDLE_FINGER_MCP"))
        index_mcp = core.point_from_record(hand_map.get("INDEX_FINGER_MCP"))
        pinky_mcp = core.point_from_record(hand_map.get("PINKY_MCP"))

        scale = core.distance_between_points(wrist, middle_mcp)
        if scale is None or scale <= 0:
            scale = core.distance_between_points(index_mcp, pinky_mcp)
        if scale is None or scale <= 0:
            scale = 80
        return scale

    def update_head_history(self, frame_record):
        offset = self.get_head_offset(frame_record)
        self.head_history.append(offset)

    def get_head_offset(self, frame_record):
        upper_body = frame_record["upper_body_landmarks"]
        nose = upper_body.get("NOSE")
        left_eye = upper_body.get("LEFT_EYE")
        right_eye = upper_body.get("RIGHT_EYE")
        if nose is None or left_eye is None or right_eye is None:
            return None

        left_eye_point = core.point_from_record(left_eye)
        right_eye_point = core.point_from_record(right_eye)
        nose_point = core.point_from_record(nose)
        eye_distance = core.distance_between_points(left_eye_point, right_eye_point)
        if eye_distance is None or eye_distance <= 0:
            return None

        center_x = (left_eye_point[0] + right_eye_point[0]) / 2
        center_y = (left_eye_point[1] + right_eye_point[1]) / 2
        return (
            (nose_point[0] - center_x) / eye_distance,
            (nose_point[1] - center_y) / eye_distance,
        )

    def detect_head_motion(self):
        offsets = [offset for offset in self.head_history if offset is not None]
        if len(offsets) < 12:
            return "WAIT"

        xs = [offset[0] for offset in offsets]
        ys = [offset[1] for offset in offsets]
        x_amplitude = max(xs) - min(xs)
        y_amplitude = max(ys) - min(ys)
        x_changes = self.count_direction_changes(xs, min_delta=0.035)
        y_changes = self.count_direction_changes(ys, min_delta=0.035)

        if y_amplitude >= 0.23 and y_changes >= 2 and y_amplitude > x_amplitude * 1.12:
            return "AGREE"
        if x_amplitude >= 0.2 and x_changes >= 2 and x_amplitude > y_amplitude * 1.12:
            return "NEGATIVE"
        return "WAIT"

    def detect_attention_state(self, frame_record):
        has_face = bool(frame_record["face_landmarks"])
        has_nose = frame_record["upper_body_landmarks"].get("NOSE") is not None
        if not has_face and not has_nose:
            self.away_frame_count += 1
        else:
            self.away_frame_count = 0

        if self.away_frame_count >= 12:
            return "AWAY"
        if not has_face:
            return "SEARCHING"

        direction = self.detect_face_direction(frame_record["upper_body_landmarks"])
        if direction == "CENTER":
            return "SCREEN"
        if direction in ("LEFT", "RIGHT"):
            return "LOOKING_AWAY"
        return "SEARCHING"

    def count_direction_changes(self, values, min_delta):
        signs = []
        for previous, current in zip(values, values[1:]):
            delta = current - previous
            if abs(delta) < min_delta:
                continue
            signs.append(1 if delta > 0 else -1)

        changes = 0
        previous_sign = None
        for sign in signs:
            if previous_sign is not None and sign != previous_sign:
                changes += 1
            previous_sign = sign
        return changes

    def get_display_hand_states(self, frame_record):
        left_state = frame_record["hand_gestures"]["left"]["state"]
        right_state = frame_record["hand_gestures"]["right"]["state"]
        if self.mirror_var.get():
            return right_state, left_state
        return left_state, right_state

    def get_hand_label_side_map(self):
        if self.mirror_var.get():
            return {"left": "right", "right": "left"}
        return None

    def detect_face_direction(self, upper_body_landmarks):
        nose = upper_body_landmarks.get("NOSE")
        left_eye = upper_body_landmarks.get("LEFT_EYE")
        right_eye = upper_body_landmarks.get("RIGHT_EYE")

        if nose is None or left_eye is None or right_eye is None:
            return "NONE"

        center_x = (left_eye["pixel_x"] + right_eye["pixel_x"]) / 2
        eye_distance = abs(right_eye["pixel_x"] - left_eye["pixel_x"])
        if eye_distance <= 0:
            return "CENTER"

        delta = nose["pixel_x"] - center_x
        threshold = eye_distance * 0.16
        if delta <= -threshold:
            return "LEFT"
        if delta >= threshold:
            return "RIGHT"
        return "CENTER"

    def update_air_paths(self, frame_record):
        for side in ("left", "right"):
            hand_records = frame_record[f"{side}_hand_landmarks"]
            if not hand_records:
                self.air_paths[side].append(None)
                self.trim_air_path(side)
                continue

            hand_map = core.records_by_name(hand_records)
            index_tip = hand_map.get("INDEX_FINGER_TIP")
            if index_tip is None:
                self.air_paths[side].append(None)
            else:
                self.air_paths[side].append((index_tip["pixel_x"], index_tip["pixel_y"]))
            self.trim_air_path(side)

    def trim_air_path(self, side):
        if len(self.air_paths[side]) > self.air_max_points:
            self.air_paths[side] = self.air_paths[side][-self.air_max_points :]

    def draw_air_paths(self, frame_bgr):
        for side, points in self.air_paths.items():
            previous = None
            for point in points:
                if point is None:
                    previous = None
                    continue
                if previous is not None:
                    cv2.line(frame_bgr, previous, point, AIR_DRAWING_COLORS[side], 3, cv2.LINE_AA)
                previous = point

    def render_frame(self, frame_bgr):
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        resized = self.fit_frame(frame_rgb, DISPLAY_WIDTH, DISPLAY_HEIGHT)
        image = Image.fromarray(resized)
        self.current_photo = ImageTk.PhotoImage(image=image)
        self.video_label.configure(image=self.current_photo)

    def fit_frame(self, frame_rgb, max_width, max_height):
        height, width = frame_rgb.shape[:2]
        scale = min(max_width / width, max_height / height)
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        return cv2.resize(frame_rgb, (new_width, new_height), interpolation=cv2.INTER_AREA)

    def on_close(self):
        self.event_client.stop()
        self.stt.stop()
        self.release_camera()
        self.holistic.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    HolisticGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
