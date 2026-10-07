"""Standalone hand landmark experiment. Run with the project's existing .venv."""
import argparse
import json
from pathlib import Path
import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton,
                            QSpinBox, QVBoxLayout, QWidget)

from renderer import LandmarkWindow
from tracker import HandTracker, Snapshot, demo_snapshot


class ControlWindow(QWidget):
    def __init__(self, display: LandmarkWindow, demo: bool = False):
        super().__init__()
        self.setWindowTitle("손 랜드마크 테스트 · 제어")
        self.setMinimumWidth(400)
        self.display = display
        self.tracker = None
        self.demo = demo
        self.closing = False
        layout = QVBoxLayout(self)
        title = QLabel("손 랜드마크 테스트")
        title.setStyleSheet("font-size: 21px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel("카메라 영상은 표시·저장·전송하지 않습니다.\n손 관절의 점과 연결선만 표시합니다."))
        row = QHBoxLayout()
        row.addWidget(QLabel("카메라 번호"))
        self.camera = QSpinBox()
        self.camera.setRange(0, 9)
        row.addWidget(self.camera)
        self.start_button = QPushButton("카메라 시작")
        self.start_button.clicked.connect(self.start_camera)
        row.addWidget(self.start_button)
        self.stop_button = QPushButton("중지")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_camera)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self.backend = QComboBox()
        for label, value in (("자동 연결 (Media Foundation 우선)", "auto"),
                             ("Media Foundation", "msmf"), ("DirectShow", "dshow"),
                             ("OpenCV 기본 연결", "any")):
            self.backend.addItem(label, value)
        layout.addWidget(self.backend)
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("최대 표시 손 수"))
        self.max_hands = QSpinBox()
        self.max_hands.setRange(1, 2)
        self.max_hands.setValue(1)
        count_row.addWidget(self.max_hands)
        layout.addLayout(count_row)
        self.mirror = QCheckBox("거울처럼 좌우 반전")
        self.mirror.setChecked(True)
        self.smooth = QCheckBox("좌표 흔들림 보정")
        self.smooth.setChecked(True)
        for box in (self.mirror, self.smooth):
            box.toggled.connect(self.configure)
            layout.addWidget(box)
        self.overlay = QCheckBox("바탕화면 위에서 손 이동 (마우스 클릭 통과)")
        self.overlay.toggled.connect(self.toggle_overlay)
        layout.addWidget(self.overlay)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("손 크기 (%)"))
        self.hand_size = QSpinBox()
        self.hand_size.setRange(50, 200)
        self.hand_size.setSingleStep(10)
        self.hand_size.setValue(100)
        self.hand_size.valueChanged.connect(self.display.set_scale)
        size_row.addWidget(self.hand_size)
        layout.addLayout(size_row)
        self.numbers = QCheckBox("관절 번호 표시")
        self.numbers.toggled.connect(self.toggle_numbers)
        layout.addWidget(self.numbers)
        self.status = QLabel("카메라 시작을 누르고 손을 보여주세요.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.stats = QLabel("인식 FPS —  ·  추론 시간 —  ·  손 0개")
        layout.addWidget(self.stats)
        layout.addWidget(QLabel("오른손: 민트색 · 왼손: 파란색 · 손끝: 노란색\n종료하면 카메라와 표시창이 함께 닫힙니다."))
        quit_button = QPushButton("테스트 종료")
        quit_button.clicked.connect(self.close)
        layout.addWidget(quit_button)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)
        if demo:
            self.display.set_snapshot(demo_snapshot())
            self.status.setText("데모 · 합성 좌표입니다. 실제 카메라 인식이 아닙니다.")

    def configure(self):
        self.display.smooth_motion = self.smooth.isChecked()
        if self.tracker:
            self.tracker.configure(self.mirror.isChecked(), self.smooth.isChecked())

    def toggle_overlay(self, enabled):
        self.display.set_overlay(enabled, self.screen())
        self.raise_()

    def toggle_numbers(self, enabled):
        self.display.numbers = enabled
        self.display.refresh_display()

    def start_camera(self):
        if self.tracker and self.tracker.running():
            return
        self.demo = False
        self.tracker = HandTracker(self.camera.value(), self.mirror.isChecked(), self.smooth.isChecked(),
                                   self.backend.currentData(), self.max_hands.value())
        self.tracker.start()
        self.camera_started = time.monotonic()
        if not self.display.overlay:
            self.display.show()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.camera.setEnabled(False)
        self.backend.setEnabled(False)
        self.max_hands.setEnabled(False)

    def stop_camera(self):
        if self.tracker:
            self.tracker.stop()
        self.stop_button.setEnabled(False)
        self.display.set_snapshot(Snapshot(status="카메라 중지 중…"))

    def refresh(self):
        if self.closing:
            if not self.tracker or not self.tracker.running():
                QApplication.instance().quit()
            return
        if not self.tracker:
            return
        snapshot = self.tracker.snapshot()
        # Hide stale hands even if camera.read() blocks or disconnects.
        if snapshot.timestamp and time.monotonic() - snapshot.timestamp > 0.3:
            from dataclasses import replace
            snapshot = replace(snapshot, hands=())
        self.display.set_snapshot(snapshot)
        self.status.setText(snapshot.error or snapshot.status)
        if not snapshot.frames and self.tracker.running() and time.monotonic() - self.camera_started > 10:
            self.status.setText("카메라 연결이 지연됩니다. 테스트를 종료한 뒤 다른 번호/연결 방식으로 다시 시도하세요.")
        self.stats.setText(f"인식 FPS {snapshot.fps:.1f}  ·  추론 {snapshot.inference_ms:.1f} ms  ·  손 {len(snapshot.hands)}개")
        running = self.tracker.running()
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.camera.setEnabled(not running)
        self.backend.setEnabled(not running)
        self.max_hands.setEnabled(not running)

    def closeEvent(self, event):
        self.closing = True
        if self.tracker:
            self.tracker.stop()
        self.display.close()
        if self.tracker and self.tracker.running():
            # Keep Qt responsive while the worker releases the camera/model.
            event.ignore()
            self.hide()
            QTimer.singleShot(3000, QApplication.instance().quit)
        else:
            event.accept()
            QApplication.instance().quit()


def probe_camera(camera: int, seconds: float, backend: str = "auto", max_hands: int = 1) -> int:
    tracker = HandTracker(camera, backend=backend, max_hands=max_hands)
    tracker.start()
    deadline = time.monotonic() + seconds
    max_hands = 0
    snapshot = tracker.snapshot()
    while time.monotonic() < deadline:
        snapshot = tracker.snapshot()
        max_hands = max(max_hands, len(snapshot.hands))
        if snapshot.error:
            break
        time.sleep(0.05)
    tracker.stop()
    tracker.join(3)
    error = snapshot.error
    if not snapshot.frames and not error:
        error = "Camera connection timed out without receiving a frame"
    if tracker.running() and not error:
        error = "Camera worker did not stop before timeout"
    report = {"camera": camera, "backend": backend, "configured_max_hands": max_hands,
              "frames": snapshot.frames, "fps": round(snapshot.fps, 1),
              "inference_ms": round(snapshot.inference_ms, 1), "max_hands": max_hands,
              "worker_stopped": not tracker.running(), "error": error}
    print(json.dumps(report, ensure_ascii=True))
    return 0 if snapshot.frames > 0 and not error and not tracker.running() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Synthetic hand; does not open a camera")
    parser.add_argument("--snapshot", type=Path, help="Save synthetic UI preview and exit (no camera)")
    parser.add_argument("--probe-camera", action="store_true", help="Read camera briefly, print metrics, then release it")
    # User confirmed camera 2 works; both controls/CLI can select another camera.
    parser.add_argument("--camera", type=int, default=2)
    parser.add_argument("--backend", choices=("auto", "msmf", "dshow", "any"), default="dshow")
    parser.add_argument("--max-hands", type=int, choices=(1, 2), default=1)
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--start-camera", action="store_true", help="Start the camera when the UI opens")
    parser.add_argument("--preview", action="store_true", help="Use the dark preview instead of desktop hands")
    parser.add_argument("--verify-live", action="store_true", help="Record hand-window counts and rendered alpha frame; keep UI open")
    args = parser.parse_args()
    if args.probe_camera:
        return probe_camera(args.camera, args.seconds, args.backend, args.max_hands)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    display = LandmarkWindow()
    control = ControlWindow(display, args.demo or bool(args.snapshot))
    control.camera.setValue(args.camera)
    control.backend.setCurrentIndex(control.backend.findData(args.backend))
    control.max_hands.setValue(args.max_hands)
    display.show()
    control.show()
    area = control.screen().availableGeometry()
    display.move(area.left() + 30, area.top() + 50)
    control.move(min(area.right() - control.width(), display.x() + display.width() + 20), area.top() + 50)
    control.overlay.setChecked(not args.preview and not args.snapshot)
    if (args.start_camera or not args.demo) and not args.snapshot:
        control.start_camera()
    if args.verify_live:
        from live_check import install
        control.live_check = install(control, args.seconds)
    if args.snapshot:
        def save():
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            ok = display.grab().save(str(args.snapshot))
            print("Synthetic preview saved" if ok else "Failed to save preview")
            app.exit(0 if ok else 1)
        QTimer.singleShot(150, save)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
