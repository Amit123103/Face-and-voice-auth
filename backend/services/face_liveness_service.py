"""
Face Liveness Detection Service — anti-spoofing for face authentication.
Blink detection, motion challenge, texture analysis, depth cues.
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

EAR_THRESHOLD = 0.21
EAR_CONSEC_FRAMES = 3
LAPLACIAN_THRESHOLD = 100.0
MIN_SYMMETRY_SCORE = 0.6


class FaceLivenessService:
    """Detects liveness to prevent face spoofing attacks."""

    def _compute_ear(self, eye_points: np.ndarray) -> float:
        """
        Compute the Eye Aspect Ratio (EAR) for a single eye.
        eye_points: array of shape (6, 2) representing the 6 eye landmarks.
        """
        v1 = np.linalg.norm(eye_points[1] - eye_points[5])
        v2 = np.linalg.norm(eye_points[2] - eye_points[4])
        h = np.linalg.norm(eye_points[0] - eye_points[3])
        if h == 0:
            return 0.0
        return (v1 + v2) / (2.0 * h)

    def detect_blink(self, ear_values: List[float]) -> Tuple[bool, int]:
        """
        Detect blinks from a sequence of EAR values over frames.

        Returns:
            Tuple of (blink_detected, blink_count)
        """
        blink_count = 0
        consecutive_below = 0

        for ear in ear_values:
            if ear < EAR_THRESHOLD:
                consecutive_below += 1
            else:
                if consecutive_below >= EAR_CONSEC_FRAMES:
                    blink_count += 1
                consecutive_below = 0

        return blink_count >= 1, blink_count

    def check_texture(self, image_gray: np.ndarray) -> Tuple[bool, float]:
        """
        Check image texture using Laplacian variance to detect printed photos.
        Real faces have higher texture variance than flat prints.
        """
        import cv2

        laplacian = cv2.Laplacian(image_gray, cv2.CV_64F)
        variance = laplacian.var()
        is_real = variance > LAPLACIAN_THRESHOLD
        score = min(variance / (LAPLACIAN_THRESHOLD * 3), 1.0)
        return is_real, round(score, 3)

    def check_motion(
        self,
        landmarks_sequence: List[np.ndarray],
        challenge: str,
    ) -> Tuple[bool, float]:
        """
        Verify head motion matches the requested challenge.
        challenge: 'nod', 'turn_left', 'turn_right'

        Args:
            landmarks_sequence: List of landmark arrays, each shape (68, 2).
            challenge: The motion challenge issued.

        Returns:
            Tuple of (motion_matched, confidence)
        """
        if len(landmarks_sequence) < 5:
            return False, 0.0

        nose_tip_idx = 30
        positions = [lm[nose_tip_idx] for lm in landmarks_sequence]

        if challenge == "nod":
            y_values = [p[1] for p in positions]
            y_range = max(y_values) - min(y_values)
            threshold = 15.0
            matched = y_range > threshold
            confidence = min(y_range / (threshold * 2), 1.0)

        elif challenge == "turn_left":
            x_values = [p[0] for p in positions]
            x_delta = max(x_values) - min(x_values)
            first_half = np.mean(x_values[: len(x_values) // 2])
            second_half = np.mean(x_values[len(x_values) // 2:])
            matched = x_delta > 20.0 and second_half < first_half
            confidence = min(x_delta / 40.0, 1.0)

        elif challenge == "turn_right":
            x_values = [p[0] for p in positions]
            x_delta = max(x_values) - min(x_values)
            first_half = np.mean(x_values[: len(x_values) // 2])
            second_half = np.mean(x_values[len(x_values) // 2:])
            matched = x_delta > 20.0 and second_half > first_half
            confidence = min(x_delta / 40.0, 1.0)

        else:
            return False, 0.0

        return matched, round(confidence, 3)

    def check_depth_cues(
        self, landmarks_sequence: List[np.ndarray]
    ) -> Tuple[bool, float]:
        """
        Analyze facial symmetry and scale consistency as depth cues.
        Flat images (photos/screens) show unnaturally consistent symmetry.
        """
        if len(landmarks_sequence) < 3:
            return False, 0.0

        symmetry_scores = []
        scale_variations = []

        for landmarks in landmarks_sequence:
            left_eye_center = np.mean(landmarks[36:42], axis=0)
            right_eye_center = np.mean(landmarks[42:48], axis=0)
            nose_tip = landmarks[30]

            left_dist = np.linalg.norm(left_eye_center - nose_tip)
            right_dist = np.linalg.norm(right_eye_center - nose_tip)

            if max(left_dist, right_dist) > 0:
                sym = min(left_dist, right_dist) / max(left_dist, right_dist)
                symmetry_scores.append(sym)

            eye_dist = np.linalg.norm(left_eye_center - right_eye_center)
            scale_variations.append(eye_dist)

        if not symmetry_scores:
            return False, 0.0

        avg_symmetry = np.mean(symmetry_scores)
        scale_std = np.std(scale_variations) if len(scale_variations) > 1 else 0

        has_natural_variation = scale_std > 0.5
        has_good_symmetry = avg_symmetry > MIN_SYMMETRY_SCORE

        passed = has_good_symmetry
        score = avg_symmetry * 0.7 + min(scale_std / 3.0, 0.3)
        return passed, round(min(score, 1.0), 3)

    async def evaluate_liveness(
        self,
        ear_values: List[float],
        gray_frames: List[np.ndarray],
        landmarks_sequence: List[np.ndarray],
        challenge: Optional[str] = None,
    ) -> Tuple[bool, float, dict]:
        """
        Run full liveness evaluation combining all checks.

        Returns:
            Tuple of (passed, overall_score, details)
        """
        blink_ok, blink_count = self.detect_blink(ear_values)

        texture_scores = []
        for gray in gray_frames[:5]:
            _, t_score = self.check_texture(gray)
            texture_scores.append(t_score)
        avg_texture = np.mean(texture_scores) if texture_scores else 0.0
        texture_ok = avg_texture > 0.3

        if challenge:
            motion_ok, motion_score = self.check_motion(landmarks_sequence, challenge)
        else:
            motion_ok, motion_score = True, 0.8

        depth_ok, depth_score = self.check_depth_cues(landmarks_sequence)

        weights = {"blink": 0.30, "texture": 0.25, "motion": 0.25, "depth": 0.20}
        overall = (
            weights["blink"] * (1.0 if blink_ok else 0.0)
            + weights["texture"] * avg_texture
            + weights["motion"] * motion_score
            + weights["depth"] * depth_score
        )
        overall = round(overall, 3)

        passed = overall >= settings.MIN_FACE_LIVENESS_SCORE

        details = {
            "blink_detected": blink_ok,
            "blink_count": blink_count,
            "texture_score": round(avg_texture, 3),
            "texture_ok": texture_ok,
            "motion_score": round(motion_score, 3),
            "motion_ok": motion_ok,
            "depth_score": round(depth_score, 3),
            "depth_ok": depth_ok,
            "overall_score": overall,
            "threshold": settings.MIN_FACE_LIVENESS_SCORE,
            "passed": passed,
        }

        if not passed:
            logger.warning(f"Face liveness check failed: {details}")

        return passed, overall, details


face_liveness_service = FaceLivenessService()
