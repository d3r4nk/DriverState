import time
import cv2
import numpy as np
import mediapipe as mp
import os
import sys

# Thêm đường dẫn để import các module
sys.path.append(os.path.join(os.path.dirname(__file__), 'driver_state_detection'))

from attention_scorer import AttentionScorer as AttScorer
from eye_detector import EyeDetector as EyeDet
from pose_estimation import HeadPoseEstimator as HeadPoseEst
from utils import get_landmarks, load_camera_parameters


class AIProcessor:
    """Class để xử lý AI cho driver state detection"""
    
    def __init__(self, camera_params=None, 
                 ear_thresh=0.15,
                 gaze_thresh=0.2,
                 roll_thresh=35,
                 pitch_thresh=35,
                 yaw_thresh=28,
                 ear_time_thresh=1.5,
                 gaze_time_thresh=2.0,
                 pose_time_thresh=2.5):
        """
        Khởi tạo AI Processor
        
        Parameters:
        -----------
        camera_params: str, optional
            Đường dẫn đến file camera parameters
        """
        # Load camera parameters nếu có
        camera_matrix = None
        dist_coeffs = None
        if camera_params and os.path.exists(camera_params):
            camera_matrix, dist_coeffs = load_camera_parameters(camera_params)
        
        # Khởi tạo MediaPipe Face Mesh
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            refine_landmarks=True,
        )
        
        # Khởi tạo các detector
        self.eye_detector = EyeDet(show_processing=False)
        self.head_pose = HeadPoseEst(
            show_axis=True,
            camera_matrix=camera_matrix,
            dist_coeffs=dist_coeffs
        )
        
        # Khởi tạo attention scorer
        t_now = time.perf_counter()
        self.att_scorer = AttScorer(
            t_now=t_now,
            ear_thresh=ear_thresh,
            gaze_thresh=gaze_thresh,
            roll_thresh=roll_thresh,
            pitch_thresh=pitch_thresh,
            yaw_thresh=yaw_thresh,
            ear_time_thresh=ear_time_thresh,
            gaze_time_thresh=gaze_time_thresh,
            pose_time_thresh=pose_time_thresh,
            verbose=False,
        )
        
        # Biến để tracking
        self.prev_time = time.perf_counter()
        self.frame_count = 0
        
    def process_frame(self, frame):
        """
        Xử lý một frame và trả về kết quả
        
        Parameters:
        -----------
        frame: numpy.ndarray
            Frame từ camera hoặc video
            
        Returns:
        --------
        dict: Kết quả xử lý bao gồm:
            - ear: Eye Aspect Ratio
            - gaze: Gaze Score
            - roll, pitch, yaw: Head pose angles
            - asleep: Trạng thái ngủ
            - looking_away: Trạng thái nhìn đi chỗ khác
            - distracted: Trạng thái mất tập trung
            - tired: Trạng thái mệt mỏi
            - perclos: PERCLOS score
            - processed_frame: Frame đã được vẽ thông tin
        """
        t_now = time.perf_counter()
        
        # Tính FPS
        elapsed_time = t_now - self.prev_time
        self.prev_time = t_now
        fps = 1.0 / elapsed_time if elapsed_time > 0 else 0.0
        
        # Copy frame để xử lý
        processed_frame = frame.copy()
        
        # Chuyển sang grayscale cho MediaPipe
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = np.expand_dims(gray, axis=2)
        gray = np.concatenate([gray, gray, gray], axis=2)
        
        # Get frame size
        frame_size = (frame.shape[1], frame.shape[0])
        
        # Khởi tạo kết quả mặc định
        result = {
            'ear': None,
            'gaze': None,
            'roll': None,
            'pitch': None,
            'yaw': None,
            'asleep': False,
            'looking_away': False,
            'distracted': False,
            'tired': False,
            'perclos': 0.0,
            'face_detected': False,
            'fps': round(fps, 2),
            'processed_frame': processed_frame
        }
        
        # Tìm faces
        lms = self.face_mesh.process(gray).multi_face_landmarks
        
        if lms:
            result['face_detected'] = True
            
            # Lấy landmarks
            landmarks = get_landmarks(lms)
            
            # Vẽ eye keypoints
            self.eye_detector.show_eye_keypoints(
                color_frame=processed_frame,
                landmarks=landmarks,
                frame_size=frame_size
            )
            
            # Tính EAR
            ear = self.eye_detector.get_EAR(landmarks=landmarks)
            result['ear'] = round(float(ear), 3) if ear is not None else None
            
            # Tính Gaze Score (cần frame gốc, không phải gray)
            gaze = self.eye_detector.get_Gaze_Score(
                frame=gray,
                landmarks=landmarks,
                frame_size=frame_size
            )
            result['gaze'] = round(float(gaze), 3) if gaze is not None else None
            
            # Tính Head Pose
            frame_det, roll, pitch, yaw = self.head_pose.get_pose(
                frame=processed_frame,
                landmarks=landmarks,
                frame_size=frame_size
            )
            
            if frame_det is not None:
                processed_frame = frame_det
            
            if roll is not None:
                result['roll'] = round(float(roll[0]), 1)
            if pitch is not None:
                result['pitch'] = round(float(pitch[0]), 1)
            if yaw is not None:
                result['yaw'] = round(float(yaw[0]), 1)
            
            # Đánh giá trạng thái
            asleep, looking_away, distracted = self.att_scorer.eval_scores(
                t_now=t_now,
                ear_score=ear,
                gaze_score=gaze,
                head_roll=roll,
                head_pitch=pitch,
                head_yaw=yaw,
            )
            
            result['asleep'] = asleep
            result['looking_away'] = looking_away
            result['distracted'] = distracted
            
            # Tính PERCLOS
            tired, perclos_score = self.att_scorer.get_rolling_PERCLOS(t_now, ear)
            result['tired'] = tired
            result['perclos'] = round(float(perclos_score), 3)
            
            # Vẽ thông tin lên frame
            self._draw_info(processed_frame, result)
        
        result['processed_frame'] = processed_frame
        return result
    
    def _draw_info(self, frame, result):
        """Vẽ thông tin lên frame"""
        y_offset = 30
        
        # EAR
        if result['ear'] is not None:
            cv2.putText(
                frame,
                f"EAR: {result['ear']}",
                (10, y_offset),
                cv2.FONT_HERSHEY_PLAIN,
                1.5,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            y_offset += 25
        
        # Gaze
        if result['gaze'] is not None:
            cv2.putText(
                frame,
                f"Gaze: {result['gaze']}",
                (10, y_offset),
                cv2.FONT_HERSHEY_PLAIN,
                1.5,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            y_offset += 25
        
        # PERCLOS
        cv2.putText(
            frame,
            f"PERCLOS: {result['perclos']}",
            (10, y_offset),
            cv2.FONT_HERSHEY_PLAIN,
            1.5,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        y_offset += 25
        
        # Head Pose
        if result['roll'] is not None:
            cv2.putText(
                frame,
                f"Roll: {result['roll']}",
                (frame.shape[1] - 150, 30),
                cv2.FONT_HERSHEY_PLAIN,
                1.2,
                (255, 0, 255),
                2,
                cv2.LINE_AA,
            )
        if result['pitch'] is not None:
            cv2.putText(
                frame,
                f"Pitch: {result['pitch']}",
                (frame.shape[1] - 150, 55),
                cv2.FONT_HERSHEY_PLAIN,
                1.2,
                (255, 0, 255),
                2,
                cv2.LINE_AA,
            )
        if result['yaw'] is not None:
            cv2.putText(
                frame,
                f"Yaw: {result['yaw']}",
                (frame.shape[1] - 150, 80),
                cv2.FONT_HERSHEY_PLAIN,
                1.2,
                (255, 0, 255),
                2,
                cv2.LINE_AA,
            )
        
        # Trạng thái cảnh báo
        warning_y = frame.shape[0] - 100
        if result['asleep']:
            cv2.putText(
                frame,
                "ASLEEP!",
                (10, warning_y),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (0, 0, 255),
                3,
                cv2.LINE_AA,
            )
            warning_y += 30
        
        if result['tired']:
            cv2.putText(
                frame,
                "TIRED!",
                (10, warning_y),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (0, 0, 255),
                3,
                cv2.LINE_AA,
            )
            warning_y += 30
        
        if result['looking_away']:
            cv2.putText(
                frame,
                "LOOKING AWAY!",
                (10, warning_y),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (0, 0, 255),
                3,
                cv2.LINE_AA,
            )
            warning_y += 30
        
        if result['distracted']:
            cv2.putText(
                frame,
                "DISTRACTED!",
                (10, warning_y),
                cv2.FONT_HERSHEY_PLAIN,
                2,
                (0, 0, 255),
                3,
                cv2.LINE_AA,
            )
        
        # FPS
        cv2.putText(
            frame,
            f"FPS: {result['fps']}",
            (frame.shape[1] - 120, frame.shape[0] - 20),
            cv2.FONT_HERSHEY_PLAIN,
            1.5,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    
    def reset(self):
        """Reset các biến tracking"""
        t_now = time.perf_counter()
        self.att_scorer = AttScorer(
            t_now=t_now,
            ear_thresh=0.15,
            gaze_thresh=0.2,
            roll_thresh=35,
            pitch_thresh=35,
            yaw_thresh=28,
            ear_time_thresh=1.5,
            gaze_time_thresh=2.0,
            pose_time_thresh=2.5,
            verbose=False,
        )
        self.prev_time = t_now
        self.frame_count = 0

