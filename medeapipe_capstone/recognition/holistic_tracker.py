import argparse
import json
import math
from pathlib import Path

import cv2
import mediapipe as mp


mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_face_mesh = mp.solutions.face_mesh
mp_hands = mp.solutions.hands
mp_holistic = mp.solutions.holistic
mp_pose = mp.solutions.pose


HAND_LANDMARK_NAMES = [
    "WRIST",
    "THUMB_CMC",
    "THUMB_MCP",
    "THUMB_IP",
    "THUMB_TIP",
    "INDEX_FINGER_MCP",
    "INDEX_FINGER_PIP",
    "INDEX_FINGER_DIP",
    "INDEX_FINGER_TIP",
    "MIDDLE_FINGER_MCP",
    "MIDDLE_FINGER_PIP",
    "MIDDLE_FINGER_DIP",
    "MIDDLE_FINGER_TIP",
    "RING_FINGER_MCP",
    "RING_FINGER_PIP",
    "RING_FINGER_DIP",
    "RING_FINGER_TIP",
    "PINKY_MCP",
    "PINKY_PIP",
    "PINKY_DIP",
    "PINKY_TIP",
]

UPPER_BODY_LANDMARK_NAMES = [
    "NOSE",
    "LEFT_EYE_INNER",
    "LEFT_EYE",
    "LEFT_EYE_OUTER",
    "RIGHT_EYE_INNER",
    "RIGHT_EYE",
    "RIGHT_EYE_OUTER",
    "LEFT_EAR",
    "RIGHT_EAR",
    "MOUTH_LEFT",
    "MOUTH_RIGHT",
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
    "LEFT_ELBOW",
    "RIGHT_ELBOW",
    "LEFT_WRIST",
    "RIGHT_WRIST",
    "LEFT_PINKY",
    "RIGHT_PINKY",
    "LEFT_INDEX",
    "RIGHT_INDEX",
    "LEFT_THUMB",
    "RIGHT_THUMB",
    "LEFT_HIP",
    "RIGHT_HIP",
]

UPPER_BODY_CONNECTIONS = [
    ("LEFT_SHOULDER", "RIGHT_SHOULDER"),
    ("LEFT_SHOULDER", "LEFT_ELBOW"),
    ("LEFT_ELBOW", "LEFT_WRIST"),
    ("RIGHT_SHOULDER", "RIGHT_ELBOW"),
    ("RIGHT_ELBOW", "RIGHT_WRIST"),
    ("LEFT_SHOULDER", "LEFT_HIP"),
    ("RIGHT_SHOULDER", "RIGHT_HIP"),
    ("LEFT_HIP", "RIGHT_HIP"),
    ("NOSE", "LEFT_SHOULDER"),
    ("NOSE", "RIGHT_SHOULDER"),
]

RPS_LABEL_COLORS = {
    "SCISSORS": (0, 255, 255),
    "ROCK": (0, 64, 255),
    "PAPER": (0, 200, 0),
    "NONE": (160, 160, 160),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Detailed face, hand, and upper-body tracking with MediaPipe Holistic."
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Optional input video path. If omitted, the script uses a webcam.",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=-1,
        help="Webcam index. Use -1 to auto-scan common indices.",
    )
    parser.add_argument(
        "--camera-backend",
        choices=["auto", "dshow", "msmf", "any"],
        default="auto",
        help="Capture backend for webcams on Windows.",
    )
    parser.add_argument(
        "--camera-width",
        type=int,
        default=1280,
        help="Requested webcam capture width.",
    )
    parser.add_argument(
        "--camera-height",
        type=int,
        default=720,
        help="Requested webcam capture height.",
    )
    parser.add_argument(
        "--output-video",
        default="output_holistic_detailed.mp4",
        help="Annotated output video path",
    )
    parser.add_argument(
        "--output-json",
        default="holistic_detailed_landmarks.json",
        help="Frame-by-frame landmark JSON path",
    )
    parser.add_argument(
        "--show-preview",
        action="store_true",
        help="Display a live preview window while processing",
    )
    parser.add_argument(
        "--draw-labels",
        action="store_true",
        help="Draw upper-body landmark labels on the output video",
    )
    parser.add_argument(
        "--tracking",
        choices=["on", "off"],
        default="on",
        help="Toggle face, upper-body, and hand tracking overlays",
    )
    parser.add_argument(
        "--rps",
        choices=["on", "off"],
        default="on",
        help="Toggle rock-paper-scissors recognition",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional frame limit for quick testing",
    )
    parser.add_argument(
        "--model-complexity",
        type=int,
        choices=[0, 1, 2],
        default=2,
        help="Pose model complexity, where 2 is the most detailed",
    )
    parser.add_argument(
        "--min-detection-confidence",
        type=float,
        default=0.5,
        help="Minimum detection confidence",
    )
    parser.add_argument(
        "--min-tracking-confidence",
        type=float,
        default=0.5,
        help="Minimum tracking confidence",
    )
    return parser.parse_args()


def ensure_parent_dir(file_path):
    Path(file_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def normalized_to_pixel_coordinates(x, y, width, height):
    return {
        "x": int(round(x * width)),
        "y": int(round(y * height)),
    }


def landmark_to_record(landmark, width, height, index, name=None):
    pixel = normalized_to_pixel_coordinates(landmark.x, landmark.y, width, height)
    record = {
        "index": index,
        "x": landmark.x,
        "y": landmark.y,
        "z": landmark.z,
        "pixel_x": pixel["x"],
        "pixel_y": pixel["y"],
    }
    if name is not None:
        record["name"] = name
    if hasattr(landmark, "visibility"):
        record["visibility"] = landmark.visibility
    if hasattr(landmark, "presence"):
        record["presence"] = landmark.presence
    return record


def landmark_list_to_records(landmark_list, width, height, names=None):
    if landmark_list is None:
        return []

    records = []
    for index, landmark in enumerate(landmark_list.landmark):
        name = names[index] if names and index < len(names) else None
        records.append(landmark_to_record(landmark, width, height, index, name=name))
    return records


def records_by_name(records):
    return {record["name"]: record for record in records if "name" in record}


def point_from_record(record):
    if record is None:
        return None
    return (record["pixel_x"], record["pixel_y"])


def distance_between_points(point_a, point_b):
    if point_a is None or point_b is None:
        return None
    return math.dist(point_a, point_b)


def angle_between_points(point_a, point_b, point_c):
    if point_a is None or point_b is None or point_c is None:
        return None

    vector_ba = (point_a[0] - point_b[0], point_a[1] - point_b[1])
    vector_bc = (point_c[0] - point_b[0], point_c[1] - point_b[1])

    magnitude_ba = math.hypot(*vector_ba)
    magnitude_bc = math.hypot(*vector_bc)
    if magnitude_ba == 0 or magnitude_bc == 0:
        return None

    cosine_value = (
        (vector_ba[0] * vector_bc[0]) + (vector_ba[1] * vector_bc[1])
    ) / (magnitude_ba * magnitude_bc)
    cosine_value = max(-1.0, min(1.0, cosine_value))
    return math.degrees(math.acos(cosine_value))


def line_tilt_degrees(point_a, point_b):
    if point_a is None or point_b is None:
        return None
    delta_x = point_b[0] - point_a[0]
    delta_y = point_b[1] - point_a[1]
    return math.degrees(math.atan2(delta_y, delta_x))


def average_point(*points):
    valid_points = [point for point in points if point is not None]
    if not valid_points:
        return None
    x = sum(point[0] for point in valid_points) / len(valid_points)
    y = sum(point[1] for point in valid_points) / len(valid_points)
    return (x, y)


def hand_anchor_point(hand_records):
    if not hand_records:
        return None

    hand_map = records_by_name(hand_records)
    wrist = hand_map.get("WRIST")
    if wrist is not None:
        return (wrist["pixel_x"], wrist["pixel_y"])

    first_record = hand_records[0]
    return (first_record["pixel_x"], first_record["pixel_y"])


def finger_is_extended(hand_map, mcp_name, pip_name, tip_name):
    mcp = hand_map.get(mcp_name)
    pip = hand_map.get(pip_name)
    tip = hand_map.get(tip_name)
    if mcp is None or pip is None or tip is None:
        return False

    mcp_point = point_from_record(mcp)
    pip_point = point_from_record(pip)
    tip_point = point_from_record(tip)

    if mcp_point is None or pip_point is None or tip_point is None:
        return False

    angle = angle_between_points(mcp_point, pip_point, tip_point)
    if angle is None:
        return False

    return angle >= 160 and tip["pixel_y"] < pip["pixel_y"] < mcp["pixel_y"]


def analyze_rps_hand_state(hand_records):
    if not hand_records:
        return {
            "state": "NONE",
            "extended_fingers": {
                "index": False,
                "middle": False,
                "ring": False,
                "pinky": False,
            },
        }

    hand_map = records_by_name(hand_records)
    extended_fingers = {
        "index": finger_is_extended(
            hand_map,
            "INDEX_FINGER_MCP",
            "INDEX_FINGER_PIP",
            "INDEX_FINGER_TIP",
        ),
        "middle": finger_is_extended(
            hand_map,
            "MIDDLE_FINGER_MCP",
            "MIDDLE_FINGER_PIP",
            "MIDDLE_FINGER_TIP",
        ),
        "ring": finger_is_extended(
            hand_map,
            "RING_FINGER_MCP",
            "RING_FINGER_PIP",
            "RING_FINGER_TIP",
        ),
        "pinky": finger_is_extended(
            hand_map,
            "PINKY_MCP",
            "PINKY_PIP",
            "PINKY_TIP",
        ),
    }

    if all(extended_fingers.values()):
        state = "PAPER"
    elif (
        extended_fingers["index"]
        and extended_fingers["middle"]
        and not extended_fingers["ring"]
        and not extended_fingers["pinky"]
    ):
        state = "SCISSORS"
    elif not any(extended_fingers.values()):
        state = "ROCK"
    else:
        state = "NONE"

    return {
        "state": state,
        "extended_fingers": extended_fingers,
    }


def disabled_rps_state():
    return {
        "state": "OFF",
        "extended_fingers": {
            "index": False,
            "middle": False,
            "ring": False,
            "pinky": False,
        },
    }


def compute_upper_body_metrics(upper_body):
    left_shoulder = point_from_record(upper_body.get("LEFT_SHOULDER"))
    right_shoulder = point_from_record(upper_body.get("RIGHT_SHOULDER"))
    left_elbow = point_from_record(upper_body.get("LEFT_ELBOW"))
    right_elbow = point_from_record(upper_body.get("RIGHT_ELBOW"))
    left_wrist = point_from_record(upper_body.get("LEFT_WRIST"))
    right_wrist = point_from_record(upper_body.get("RIGHT_WRIST"))
    left_hip = point_from_record(upper_body.get("LEFT_HIP"))
    right_hip = point_from_record(upper_body.get("RIGHT_HIP"))
    left_eye = point_from_record(upper_body.get("LEFT_EYE"))
    right_eye = point_from_record(upper_body.get("RIGHT_EYE"))
    nose = point_from_record(upper_body.get("NOSE"))

    shoulder_center = average_point(left_shoulder, right_shoulder)
    hip_center = average_point(left_hip, right_hip)

    metrics = {
        "shoulder_width_px": distance_between_points(left_shoulder, right_shoulder),
        "hip_width_px": distance_between_points(left_hip, right_hip),
        "torso_height_px": distance_between_points(shoulder_center, hip_center),
        "left_upper_arm_length_px": distance_between_points(left_shoulder, left_elbow),
        "left_forearm_length_px": distance_between_points(left_elbow, left_wrist),
        "right_upper_arm_length_px": distance_between_points(right_shoulder, right_elbow),
        "right_forearm_length_px": distance_between_points(right_elbow, right_wrist),
        "left_elbow_angle_deg": angle_between_points(left_shoulder, left_elbow, left_wrist),
        "right_elbow_angle_deg": angle_between_points(right_shoulder, right_elbow, right_wrist),
        "left_shoulder_angle_deg": angle_between_points(left_hip, left_shoulder, left_elbow),
        "right_shoulder_angle_deg": angle_between_points(right_hip, right_shoulder, right_elbow),
        "shoulder_line_tilt_deg": line_tilt_degrees(left_shoulder, right_shoulder),
        "eye_line_tilt_deg": line_tilt_degrees(left_eye, right_eye),
        "head_to_shoulder_center_px": distance_between_points(nose, shoulder_center),
    }

    if shoulder_center is not None:
        metrics["shoulder_center_px"] = {
            "x": round(shoulder_center[0], 2),
            "y": round(shoulder_center[1], 2),
        }
    if hip_center is not None:
        metrics["hip_center_px"] = {
            "x": round(hip_center[0], 2),
            "y": round(hip_center[1], 2),
        }

    return metrics


def frame_summary(
    face_records,
    pose_records,
    left_hand_records,
    right_hand_records,
    left_hand_state,
    right_hand_state,
    tracking_enabled,
    rps_enabled,
):
    return {
        "face_landmark_count": len(face_records),
        "pose_landmark_count": len(pose_records),
        "left_hand_landmark_count": len(left_hand_records),
        "right_hand_landmark_count": len(right_hand_records),
        "has_face": bool(face_records),
        "has_pose": bool(pose_records),
        "has_left_hand": bool(left_hand_records),
        "has_right_hand": bool(right_hand_records),
        "left_hand_state": left_hand_state,
        "right_hand_state": right_hand_state,
        "tracking_enabled": tracking_enabled,
        "rps_enabled": rps_enabled,
    }


def draw_upper_body_overlay(frame, upper_body, draw_labels=False):
    for start_name, end_name in UPPER_BODY_CONNECTIONS:
        start_point = point_from_record(upper_body.get(start_name))
        end_point = point_from_record(upper_body.get(end_name))
        if start_point is None or end_point is None:
            continue
        cv2.line(frame, start_point, end_point, (0, 255, 255), 2, cv2.LINE_AA)

    for name, record in upper_body.items():
        point = point_from_record(record)
        if point is None:
            continue
        cv2.circle(frame, point, 4, (0, 128, 255), -1, cv2.LINE_AA)
        if draw_labels:
            cv2.putText(
                frame,
                name,
                (point[0] + 6, point[1] - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )


def draw_hand_gesture_labels(frame, frame_record, rps_enabled, hand_label_side_map=None):
    if not rps_enabled:
        return

    for side in ("left", "right"):
        gesture = frame_record["hand_gestures"][side]
        records = frame_record[f"{side}_hand_landmarks"]
        anchor = hand_anchor_point(records)
        if anchor is None:
            continue

        state = gesture["state"]
        color = RPS_LABEL_COLORS.get(state, (255, 255, 255))
        display_side = hand_label_side_map.get(side, side) if hand_label_side_map else side
        label = f"{display_side.title()}: {state}"
        text_origin = (anchor[0] + 10, max(30, anchor[1] - 12))

        cv2.putText(
            frame,
            label,
            text_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )


def draw_frame_info(frame, frame_index, summary, metrics):
    tracking_status = "ON" if summary["tracking_enabled"] else "OFF"
    rps_status = "ON" if summary["rps_enabled"] else "OFF"
    info_lines = [
        f"Frame: {frame_index}",
        f"Tracking: {tracking_status}",
        f"RPS: {rps_status}",
    ]

    if summary["tracking_enabled"]:
        info_lines.append(
            "Face/Pose/Hands: "
            f"{summary['face_landmark_count']}/"
            f"{summary['pose_landmark_count']}/"
            f"{summary['left_hand_landmark_count'] + summary['right_hand_landmark_count']}"
        )

    if summary["rps_enabled"]:
        info_lines.append(f"L/R RPS: {summary['left_hand_state']} / {summary['right_hand_state']}")

    if summary["tracking_enabled"] and metrics.get("left_elbow_angle_deg") is not None:
        info_lines.append(f"Left elbow: {metrics['left_elbow_angle_deg']:.1f} deg")
    if summary["tracking_enabled"] and metrics.get("right_elbow_angle_deg") is not None:
        info_lines.append(f"Right elbow: {metrics['right_elbow_angle_deg']:.1f} deg")
    if summary["tracking_enabled"] and metrics.get("shoulder_line_tilt_deg") is not None:
        info_lines.append(f"Shoulder tilt: {metrics['shoulder_line_tilt_deg']:.1f} deg")

    y = 24
    for line in info_lines:
        cv2.putText(
            frame,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        y += 24


def build_frame_record(frame_index, timestamp_ms, width, height, results, tracking_enabled, rps_enabled):
    face_records = landmark_list_to_records(results.face_landmarks, width, height)
    pose_names = [landmark.name for landmark in mp_pose.PoseLandmark]
    pose_records = landmark_list_to_records(results.pose_landmarks, width, height, names=pose_names)
    left_hand_records = landmark_list_to_records(
        results.left_hand_landmarks,
        width,
        height,
        names=HAND_LANDMARK_NAMES,
    )
    right_hand_records = landmark_list_to_records(
        results.right_hand_landmarks,
        width,
        height,
        names=HAND_LANDMARK_NAMES,
    )

    upper_body = {
        name: record
        for name, record in records_by_name(pose_records).items()
        if name in UPPER_BODY_LANDMARK_NAMES
    }
    metrics = compute_upper_body_metrics(upper_body)
    if rps_enabled:
        left_hand_gesture = analyze_rps_hand_state(left_hand_records)
        right_hand_gesture = analyze_rps_hand_state(right_hand_records)
    else:
        left_hand_gesture = disabled_rps_state()
        right_hand_gesture = disabled_rps_state()

    summary = frame_summary(
        face_records,
        pose_records,
        left_hand_records,
        right_hand_records,
        left_hand_gesture["state"],
        right_hand_gesture["state"],
        tracking_enabled,
        rps_enabled,
    )

    return {
        "frame_index": frame_index,
        "timestamp_ms": timestamp_ms,
        "image_size": {"width": width, "height": height},
        "summary": summary,
        "face_landmarks": face_records,
        "pose_landmarks": pose_records,
        "upper_body_landmarks": upper_body,
        "left_hand_landmarks": left_hand_records,
        "right_hand_landmarks": right_hand_records,
        "hand_gestures": {
            "left": left_hand_gesture,
            "right": right_hand_gesture,
        },
        "upper_body_metrics": metrics,
    }


def annotate_frame(
    frame,
    frame_record,
    results,
    tracking_enabled,
    rps_enabled,
    draw_labels=False,
    show_info_overlay=True,
    hand_label_side_map=None,
):
    annotated = frame.copy()

    if tracking_enabled and results.face_landmarks:
        mp_drawing.draw_landmarks(
            annotated,
            results.face_landmarks,
            mp_face_mesh.FACEMESH_TESSELATION,
            landmark_drawing_spec=None,
            connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_tesselation_style(),
        )
        mp_drawing.draw_landmarks(
            annotated,
            results.face_landmarks,
            mp_face_mesh.FACEMESH_CONTOURS,
            landmark_drawing_spec=None,
            connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_contours_style(),
        )
        mp_drawing.draw_landmarks(
            annotated,
            results.face_landmarks,
            mp_face_mesh.FACEMESH_IRISES,
            landmark_drawing_spec=None,
            connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_iris_connections_style(),
        )

    if tracking_enabled and results.pose_landmarks:
        mp_drawing.draw_landmarks(
            annotated,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style(),
        )

    if tracking_enabled and results.left_hand_landmarks:
        mp_drawing.draw_landmarks(
            annotated,
            results.left_hand_landmarks,
            mp_hands.HAND_CONNECTIONS,
            mp_drawing_styles.get_default_hand_landmarks_style(),
            mp_drawing_styles.get_default_hand_connections_style(),
        )

    if tracking_enabled and results.right_hand_landmarks:
        mp_drawing.draw_landmarks(
            annotated,
            results.right_hand_landmarks,
            mp_hands.HAND_CONNECTIONS,
            mp_drawing_styles.get_default_hand_landmarks_style(),
            mp_drawing_styles.get_default_hand_connections_style(),
        )

    if tracking_enabled:
        draw_upper_body_overlay(
            annotated,
            frame_record["upper_body_landmarks"],
            draw_labels=draw_labels,
        )

    draw_hand_gesture_labels(annotated, frame_record, rps_enabled, hand_label_side_map)
    if show_info_overlay:
        draw_frame_info(
            annotated,
            frame_record["frame_index"],
            frame_record["summary"],
            frame_record["upper_body_metrics"],
        )
    return annotated


def webcam_backends(backend_name):
    if backend_name == "dshow":
        return [("DirectShow", cv2.CAP_DSHOW)]
    if backend_name == "msmf":
        return [("Media Foundation", cv2.CAP_MSMF)]
    if backend_name == "any":
        return [("Any", cv2.CAP_ANY)]
    return [
        ("DirectShow", cv2.CAP_DSHOW),
        ("Media Foundation", cv2.CAP_MSMF),
        ("Any", cv2.CAP_ANY),
    ]


def try_open_webcam(index, backend, backend_label, width, height):
    if backend == cv2.CAP_ANY:
        cap = cv2.VideoCapture(index)
    else:
        cap = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        cap.release()
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    has_frame, frame_bgr = cap.read()
    if not has_frame or frame_bgr is None:
        cap.release()
        return None

    return {
        "cap": cap,
        "frame": frame_bgr,
        "index": index,
        "backend": backend,
        "backend_label": backend_label,
    }


def discover_webcams(args):
    candidates = []
    seen_indices = set()

    for backend_label, backend in webcam_backends(args.camera_backend):
        for index in range(6):
            if index in seen_indices:
                continue

            result = try_open_webcam(
                index,
                backend,
                backend_label,
                args.camera_width,
                args.camera_height,
            )
            if result is None:
                continue

            result["cap"].release()
            del result["cap"]
            del result["frame"]
            candidates.append(result)
            seen_indices.add(index)

    return candidates


def select_webcam_candidate(candidates):
    print("Available webcams:")
    for option_number, candidate in enumerate(candidates, start=1):
        print(
            f"  {option_number}. camera index {candidate['index']} "
            f"via {candidate['backend_label']}"
        )

    while True:
        selected = input("Select a webcam number and press Enter: ").strip()
        if not selected:
            return candidates[0]
        if selected.isdigit():
            option_number = int(selected)
            if 1 <= option_number <= len(candidates):
                return candidates[option_number - 1]
        print("Invalid selection. Please enter one of the listed numbers.")


def open_webcam(args):
    if args.camera_index >= 0:
        for backend_label, backend in webcam_backends(args.camera_backend):
            result = try_open_webcam(
                args.camera_index,
                backend,
                backend_label,
                args.camera_width,
                args.camera_height,
            )
            if result is not None:
                source_label = f"webcam index {args.camera_index} via {backend_label}"
                return result["cap"], result["frame"], source_label

        raise RuntimeError(
            f"Could not open webcam index {args.camera_index}. "
            "Try another index or remove --camera-index to choose interactively."
        )

    candidates = discover_webcams(args)
    if not candidates:
        raise RuntimeError(
            "Could not find any webcams. "
            "If you want to process a file instead, pass --input <video_path>."
        )

    selected_candidate = candidates[0] if len(candidates) == 1 else select_webcam_candidate(candidates)
    result = try_open_webcam(
        selected_candidate["index"],
        selected_candidate["backend"],
        selected_candidate["backend_label"],
        args.camera_width,
        args.camera_height,
    )
    if result is None:
        raise RuntimeError("The selected webcam could not be opened.")

    source_label = (
        f"webcam index {selected_candidate['index']} "
        f"via {selected_candidate['backend_label']}"
    )
    return result["cap"], result["frame"], source_label


def open_capture(args):
    if args.input:
        cap = cv2.VideoCapture(args.input)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open input video: {args.input}")

        has_frame, frame_bgr = cap.read()
        if not has_frame or frame_bgr is None:
            cap.release()
            raise RuntimeError(f"Could not read frames from input video: {args.input}")

        return cap, frame_bgr, f"video file: {args.input}", False

    cap, frame_bgr, source_label = open_webcam(args)
    return cap, frame_bgr, source_label, True


def main():
    args = parse_args()
    ensure_parent_dir(args.output_video)
    ensure_parent_dir(args.output_json)
    tracking_enabled = args.tracking == "on"
    rps_enabled = args.rps == "on"

    cap, pending_frame_bgr, source_label, is_webcam_source = open_capture(args)
    print(f"Using source: {source_label}")
    print(f"Tracking overlay: {'ON' if tracking_enabled else 'OFF'}")
    print(f"RPS recognition: {'ON' if rps_enabled else 'OFF'}")

    preview_enabled = args.show_preview or is_webcam_source
    window_name = "Detailed Holistic Tracking"
    if preview_enabled:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        print("Preview window enabled. Press ESC or Q to quit.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    height, width = pending_frame_bgr.shape[:2]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.output_video, fourcc, fps, (width, height))

    all_frames = []
    frame_index = 0

    try:
        with mp_holistic.Holistic(
            static_image_mode=False,
            model_complexity=args.model_complexity,
            smooth_landmarks=True,
            enable_segmentation=False,
            refine_face_landmarks=True,
            min_detection_confidence=args.min_detection_confidence,
            min_tracking_confidence=args.min_tracking_confidence,
        ) as holistic:
            while True:
                if pending_frame_bgr is not None:
                    has_frame = True
                    frame_bgr = pending_frame_bgr
                    pending_frame_bgr = None
                else:
                    has_frame, frame_bgr = cap.read()

                if not has_frame:
                    break

                if args.max_frames is not None and frame_index >= args.max_frames:
                    break

                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                frame_rgb.flags.writeable = False
                results = holistic.process(frame_rgb)
                frame_rgb.flags.writeable = True

                timestamp_ms = int((frame_index / fps) * 1000)
                frame_record = build_frame_record(
                    frame_index,
                    timestamp_ms,
                    width,
                    height,
                    results,
                    tracking_enabled,
                    rps_enabled,
                )
                annotated = annotate_frame(
                    frame_bgr,
                    frame_record,
                    results,
                    tracking_enabled,
                    rps_enabled,
                    draw_labels=args.draw_labels,
                )

                writer.write(annotated)
                all_frames.append(frame_record)

                if preview_enabled:
                    cv2.imshow(window_name, annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q"), ord("Q")):
                        break

                frame_index += 1
    finally:
        cap.release()
        writer.release()
        cv2.destroyAllWindows()

    with open(args.output_json, "w", encoding="utf-8") as output_file:
        json.dump(all_frames, output_file, ensure_ascii=False, indent=2)

    print(f"Annotated video saved to: {args.output_video}")
    print(f"Landmark JSON saved to: {args.output_json}")
    print(f"Processed frames: {len(all_frames)}")


if __name__ == "__main__":
    main()
