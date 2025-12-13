import time

import cv2
import mediapipe as mp
import numpy as np
from ultralytics import YOLO

from attention_scorer import AttentionScorer as AttScorer
from eye_detector import EyeDetector as EyeDet
from parser import get_args
from pose_estimation import HeadPoseEstimator as HeadPoseEst
from utils import get_landmarks, load_camera_parameters


def main():
    args = get_args()

    # 1) Load thông số camera (nếu có truyền vào)
    camera_matrix = None
    dist_coeffs = None
    if args.camera_params is not None:
        camera_matrix, dist_coeffs = load_camera_parameters(args.camera_params)

    # 2) Khởi tạo các module sẵn có của repo
    eye_detector = EyeDet(show_processing=args.show_eye_proc)
    head_pose_est = HeadPoseEst(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        show_axis=args.show_axis,
    )

    t0 = time.time()
    att_scorer = AttScorer(
        t_now=t0,
        ear_thresh=args.ear_thresh,
        gaze_thresh=args.gaze_thresh,
        roll_thresh=args.roll_thresh,
        pitch_thresh=args.pitch_thresh,
        yaw_thresh=args.yaw_thresh,
        ear_time_thresh=args.ear_time_thresh,
        gaze_time_thresh=args.gaze_time_thresh,
        pose_time_thresh=args.pose_time_thresh,
        verbose=args.verbose,
    )

    # 3) Khởi tạo YOLOv8 (chọn model nhẹ, ví dụ yolov8n)
    #    Đặt đường dẫn đúng tới file .pt của bạn nếu khác.
    yolo_model = YOLO("D:\\Driver-State-Detection\\driver_state_detection\\best.pt")

    # 4) Mở webcam
    cap = cv2.VideoCapture(args.camera)

    mp_face_mesh = mp.solutions.face_mesh
    with mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,         # dùng iris landmarks cho tính gaze
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as face_mesh:

        start_time = time.time()
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Lật ngang nếu dùng webcam máy tính
            if args.camera == 0:
                frame = cv2.flip(frame, 2)

            frame_h, frame_w = frame.shape[:2]
            frame_size = (frame_w, frame_h)

            frame_count += 1
            now = time.time()
            elapsed_total = now - start_time
            fps = frame_count / elapsed_total if elapsed_total > 0 else 0.0

            # --------------------------------------------------
            # 5) MEDIAPIPE FACEMESH + TÍNH TRẠNG THÁI TÀI XẾ
            # --------------------------------------------------
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb_frame)

            ear_score = None
            gaze_score = None
            yaw = pitch = roll = None

            if results.multi_face_landmarks:
                # Lấy landmark của mặt lớn nhất
                landmarks = get_landmarks(results.multi_face_landmarks)

                # Vẽ các điểm keypoint trên mắt (giống code cũ)
                eye_detector.show_eye_keypoints(
                    color_frame=frame,
                    landmarks=landmarks,
                    frame_size=frame_size,
                )

                # EAR (Eye Aspect Ratio)
                ear_score = eye_detector.get_EAR(landmarks)

                # Gaze score (mắt nhìn lệch hay không)
                gaze_score = eye_detector.get_Gaze_Score(frame, landmarks, frame_size)

                # Head pose (yaw, pitch, roll) + vẽ trục trên mặt
                frame, yaw, pitch, roll = head_pose_est.get_pose(
                    frame, landmarks, frame_size
                )

            # Đánh giá trạng thái theo thời gian
            asleep = False
            looking_away = False
            distracted = False

            if (
                ear_score is not None
                or gaze_score is not None
                or yaw is not None
                or pitch is not None
                or roll is not None
            ):
                asleep, looking_away, distracted = att_scorer.eval_scores(
                    now, ear_score, gaze_score, roll, pitch, yaw
                )

            # PERCLOS (tired)
            tired, perclos_score = att_scorer.get_PERCLOS(now, fps, ear_score)

            # --------------------------------------------------
            # 6) VẼ TEXT TRẠNG THÁI TÀI XẾ LÊN FRAME
            # --------------------------------------------------
            text_y = 30
            if args.show_fps:
                cv2.putText(
                    frame,
                    f"FPS: {fps:.1f}",
                    (10, text_y),
                    cv2.FONT_HERSHEY_PLAIN,
                    1.0,
                    (255, 255, 0),
                    1,
                    cv2.LINE_AA,
                )
                text_y += 20

            if asleep:
                cv2.putText(
                    frame,
                    "ASLEEP",
                    (10, text_y),
                    cv2.FONT_HERSHEY_PLAIN,
                    1.2,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                text_y += 25

            if tired:
                cv2.putText(
                    frame,
                    f"TIRED (PERCLOS={perclos_score:.2f})",
                    (10, text_y),
                    cv2.FONT_HERSHEY_PLAIN,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                text_y += 25

            if looking_away:
                cv2.putText(
                    frame,
                    "LOOKING AWAY",
                    (10, text_y),
                    cv2.FONT_HERSHEY_PLAIN,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                text_y += 25

            if distracted:
                cv2.putText(
                    frame,
                    "DISTRACTED",
                    (10, text_y),
                    cv2.FONT_HERSHEY_PLAIN,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                text_y += 25

            # --------------------------------------------------
            # 7) YOLOv8: PHÁT HIỆN VẬT THỂ TRÊN CÙNG FRAME
            # --------------------------------------------------
            # Chạy YOLO trên frame đã có overlay (trục đầu + text)
            yolo_results = yolo_model(frame, verbose=False)

            # Vẽ bounding box + label của YOLO lên frame
            # result.plot() sẽ giữ nguyên nội dung ảnh gốc và vẽ thêm box/label
            frame = yolo_results[0].plot()

            # --------------------------------------------------
            # 8) HIỂN THỊ
            # --------------------------------------------------
            cv2.imshow("Driver state + YOLOv8", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
