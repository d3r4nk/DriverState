import time
import numpy as np


class AttentionScorer:
    def __init__(
        self,
        t_now,
        ear_thresh,
        gaze_thresh,
        perclos_thresh=0.2,
        roll_thresh=60,
        pitch_thresh=20,
        yaw_thresh=30,
        ear_time_thresh=4.0,
        gaze_time_thresh=2.0,
        pose_time_thresh=4.0,
        decay_factor=0.9,
        verbose=False,
    ):
        self.ear_thresh = ear_thresh
        self.gaze_thresh = gaze_thresh
        self.perclos_thresh = perclos_thresh
        self.roll_thresh = roll_thresh
        self.pitch_thresh = pitch_thresh
        self.yaw_thresh = yaw_thresh
        self.ear_time_thresh = ear_time_thresh
        self.gaze_time_thresh = gaze_time_thresh
        self.pose_time_thresh = pose_time_thresh
        self.decay_factor = decay_factor
        self.verbose = verbose

        self.last_eval_time = t_now
        self.closure_time = 0.0
        self.not_look_ahead_time = 0.0
        self.distracted_time = 0.0

        self.PERCLOS_TIME_PERIOD = 60
        self.timestamps = np.empty((0,), dtype=np.float64)
        self.closed_flags = np.empty((0,), dtype=bool)
        self.eye_closure_counter = 0
        self.prev_time = t_now

    def _update_metric(self, metric_value, condition, elapsed):
        if condition:
            return metric_value + elapsed
        else:
            return metric_value * self.decay_factor

    def eval_scores(
        self, t_now, ear_score, gaze_score, head_roll, head_pitch, head_yaw
    ):
        elapsed = t_now - self.last_eval_time
        self.last_eval_time = t_now

        self.closure_time = self._update_metric(
            self.closure_time,
            (ear_score is not None and ear_score <= self.ear_thresh),
            elapsed,
        )

        self.not_look_ahead_time = self._update_metric(
            self.not_look_ahead_time,
            (gaze_score is not None and gaze_score > self.gaze_thresh),
            elapsed,
        )

        head_condition = (
            (head_roll is not None and abs(head_roll) > self.roll_thresh)
            or (head_pitch is not None and abs(head_pitch) > self.pitch_thresh)
            or (head_yaw is not None and abs(head_yaw) > self.yaw_thresh)
        )

        self.distracted_time = self._update_metric(
            self.distracted_time, head_condition, elapsed
        )

        asleep = self.closure_time >= self.ear_time_thresh
        looking_away = self.not_look_ahead_time >= self.gaze_time_thresh
        distracted = self.distracted_time >= self.pose_time_thresh

        if self.verbose:
            print(
                f"Closure Time: {self.closure_time:.2f}s | "
                f"Not Look Ahead Time: {self.not_look_ahead_time:.2f}s | "
                f"Distracted Time: {self.distracted_time:.2f}s"
            )

        return asleep, looking_away, distracted

    def get_PERCLOS(self, t_now, fps, ear_score):
        delta = t_now - self.prev_time
        tired = False

        all_frames_numbers_in_perclos_duration = int(
            self.PERCLOS_TIME_PERIOD * fps
        )

        if (ear_score is not None) and (ear_score <= self.ear_thresh):
            self.eye_closure_counter += 1

        perclos_score = (
            self.eye_closure_counter
            / all_frames_numbers_in_perclos_duration
        )

        if perclos_score >= self.perclos_thresh:
            tired = True

        if delta >= self.PERCLOS_TIME_PERIOD:
            self.eye_closure_counter = 0
            self.prev_time = t_now

        return tired, perclos_score

    def get_rolling_PERCLOS(self, t_now, ear_score):
        eye_closed = (ear_score is not None) and (ear_score <= self.ear_thresh)

        self.timestamps = np.concatenate((self.timestamps, [t_now]))
        self.closed_flags = np.concatenate((self.closed_flags, [eye_closed]))

        valid_mask = self.timestamps >= (t_now - self.PERCLOS_TIME_PERIOD)
        self.timestamps = self.timestamps[valid_mask]
        self.closed_flags = self.closed_flags[valid_mask]

        total_frames = self.timestamps.size
        if total_frames > 0:
            perclos_score = np.sum(self.closed_flags) / total_frames
        else:
            perclos_score = 0.0

        tired = perclos_score >= self.perclos_thresh
        return tired, perclos_score
