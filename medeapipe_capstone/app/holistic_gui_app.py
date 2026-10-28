"""Optional standalone diagnostic view; integrated execution uses RecognitionEngine."""
from datetime import datetime
from pathlib import Path
import tkinter as tk
import time
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk
from app.project_version import __version__
from app.recognition_engine import (
    RecognitionEngine,
    core,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
    PROJECT_ROOT,
    EMOTION_MODEL_PATH,
    EMOTIEFF_MODEL_PATH,
    EMOTION_MODEL_OPTIONS,
    EMOTION_INFERENCE_INTERVAL_MS,
    EMOTION_CPU_THREADS,
    EMOTION_NEUTRAL_CONFIDENCE_THRESHOLD,
    EMOTION_NEUTRAL_MARGIN_THRESHOLD,
    AIR_DRAWING_COLORS,
    LABEL_CAMERA,
    LABEL_REFRESH,
    LABEL_START,
    LABEL_MODE,
    LABEL_RPS,
    LABEL_CHAM,
    LABEL_AIR,
    LABEL_WAVE,
    LABEL_HAND_GESTURE,
    LABEL_HEAD_GESTURE,
    LABEL_ATTENTION,
    LABEL_TOGGLES,
    LABEL_TRACKING,
    LABEL_MARKER_ONLY,
    LABEL_MIRROR,
    LABEL_INFO_OVERLAY,
    LABEL_EMOTION,
    LABEL_STATUS,
    LABEL_ALWAYS_RECOGNITION,
    LABEL_STT,
    LABEL_MIC,
    LABEL_STT_REFRESH,
    LABEL_STT_START,
    LABEL_STT_STOP,
    LABEL_STT_SAVE,
    LABEL_STT_CLEAR,
    LABEL_STT_RESULT,
    MODE_LABELS,
)


class HolisticGuiApp(RecognitionEngine):
    def __init__(self, root, background_mode=False, command_stream=None):
        self.root = root
        root.title(f"Holistic Tracking GUI v{__version__}")
        root.geometry("1420x860")
        root.configure(bg="#101418")
        super().__init__(root, background_mode=background_mode, command_stream=command_stream)

    def make_value(self, value):
        factory = tk.BooleanVar if isinstance(value, bool) else tk.StringVar
        return factory(master=self.root, value=value)

    def prepare_presentation(self):
        self.build_ui()
        self.show_placeholder('카메라를 시작하면 인식 화면이 여기에 표시됩니다.')
        self.root.protocol('WM_DELETE_WINDOW', self.hide_console if self.background_mode else self.on_close)
        if self.background_mode:
            self.root.withdraw()

    def preview_visible(self):
        return bool(self.root.winfo_viewable())

    def prepare_camera_choices(self):
        self.refresh_cameras()

    def camera_choices_changed(self):
        menu = self.camera_menu['menu']
        menu.delete(0, 'end')
        for candidate in self.camera_candidates:
            label = f"index {candidate['index']} / {candidate['backend_label']}"
            menu.add_command(label=label, command=lambda value=label: self.camera_var.set(value))

    def microphone_choices_changed(self, labels):
        menu = self.stt_mic_menu['menu']
        menu.delete(0, 'end')
        for label in labels:
            menu.add_command(label=label, command=lambda value=label: self.select_stt_microphone(value))

    def stt_running_changed(self, running):
        self.stt_start_button.configure(state='disabled' if running else 'normal')
        self.stt_stop_button.configure(state='normal' if running else 'disabled')

    def report_error(self, title, message):
        messagebox.showerror(title, message)

    def show_console(self):
        """숨겨진 사용자 인식 콘솔을 복원해 화면 앞으로 가져온다."""
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()


    def hide_console(self):
        """GUI만 숨기고 카메라와 인식 루프는 계속 실행한다."""
        self.root.withdraw()


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
            command=self.start_full_camera_discovery,
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

        self.make_toggle(toggle_frame, LABEL_TRACKING, self.tracking_var, self.save_recognition_settings).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_MARKER_ONLY, self.marker_only_var, self.save_recognition_settings).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_MIRROR, self.mirror_var, self.save_recognition_settings).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_INFO_OVERLAY, self.info_overlay_var, self.save_recognition_settings).pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_EMOTION, self.emotion_var, self.save_recognition_settings).pack(fill="x", pady=(0, 8))
        self.emotion_model_menu = tk.OptionMenu(
            toggle_frame,
            self.emotion_model_var,
            *EMOTION_MODEL_OPTIONS,
            command=self.change_emotion_model,
        )
        self.style_option_menu(self.emotion_model_menu)
        self.emotion_model_menu.pack(fill="x", pady=(0, 8))
        self.make_toggle(toggle_frame, LABEL_ALWAYS_RECOGNITION, self.always_recognition_var, self.save_recognition_settings).pack(fill="x")

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
        self.make_small_option(stt_option_row, self.stt_provider_var, PROVIDER_OPTIONS, self.save_stt_device_settings).pack(side="left", fill="x", expand=True)
        self.make_small_option(stt_option_row, self.stt_language_var, LANGUAGE_OPTIONS, self.save_stt_device_settings).pack(side="left", fill="x", expand=True, padx=(8, 0))

        stt_turn_row = tk.Frame(control_panel, bg="#161c22")
        stt_turn_row.pack(fill="x", padx=18, pady=(0, 8))
        self.make_small_option(stt_turn_row, self.stt_sensitivity_var, SENSITIVITY_OPTIONS, self.save_stt_device_settings).pack(side="left", fill="x", expand=True)
        self.make_small_option(stt_turn_row, self.stt_silence_var, SILENCE_OPTIONS, self.save_stt_device_settings).pack(side="left", fill="x", expand=True, padx=(8, 0))

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

        self.make_toggle(control_panel, "\ud0c0\uc784\uc2a4\ud0ec\ud504 \ud45c\uc2dc", self.stt_timestamps_var, self.save_stt_device_settings).pack(fill="x", padx=18, pady=(0, 8))
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


    def make_toggle(self, parent, text, variable, command=None):
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
            command=command,
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


    def make_small_option(self, parent, variable, values, command=None):
        callback = (lambda _value: command()) if command is not None else None
        option = tk.OptionMenu(parent, variable, *values, command=callback)
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


    def update_mode_buttons(self):
        for mode_key, button in self.mode_buttons.items():
            if mode_key == self.active_mode:
                button.configure(bg="#7fd1b9", fg="#0d141a")
            else:
                button.configure(bg="#24303d", fg="#f4f7fb")


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


def main(background_mode=False, command_stream=None):
    root = tk.Tk()
    HolisticGuiApp(
        root,
        background_mode=background_mode,
        command_stream=command_stream,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
