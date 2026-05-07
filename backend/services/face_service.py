"""
Face Recognition Service — dlib-based 128-d face encoding with multi-angle enrollment.
Stores only encrypted encodings, never raw images.
Optimized for speed: thread pool for CPU-bound work, vectorized distance computation.
"""

import asyncio
import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import numpy as np

from backend.config import get_settings
from backend.services.encryption_service import encryption_service

settings = get_settings()
logger = logging.getLogger(__name__)

VALID_ANGLES = ["front", "left_30", "right_30", "up_15", "down_15"]

_face_detector = None
_shape_predictor = None
_face_recognizer = None
_models_loaded = False

# Thread pool for CPU-bound face processing (encoding, detection)
_face_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="face")


def _load_models() -> bool:
    """Lazy-load dlib models on first use."""
    global _face_detector, _shape_predictor, _face_recognizer, _models_loaded

    if _models_loaded:
        return True

    try:
        import dlib

        _face_detector = dlib.get_frontal_face_detector()

        predictor_path = f"{settings.FACE_MODEL_DIR}/shape_predictor_68_face_landmarks.dat"
        _shape_predictor = dlib.shape_predictor(predictor_path)

        recognizer_path = f"{settings.FACE_MODEL_DIR}/dlib_face_recognition_resnet_model_v1.dat"
        _face_recognizer = dlib.face_recognition_model_v1(recognizer_path)

        _models_loaded = True
        logger.info("Face recognition models loaded successfully")
        return True
    except Exception as e:
        logger.warning(f"Face models not available: {e}. Using simulation mode.")
        _models_loaded = False
        return False


class FaceService:
    """Handles face encoding, enrollment, and verification."""

    def __init__(self) -> None:
        self._models_ready = _load_models()

    @property
    def is_ready(self) -> bool:
        """Check if face recognition models are loaded."""
        return self._models_ready

    def _decode_image(self, image_b64: str) -> np.ndarray:
        """Decode a base64 image string to a numpy array."""
        import cv2

        image_data = base64.b64decode(image_b64)
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image")
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def _detect_faces(self, image: np.ndarray) -> list:
        """Detect faces in an image using dlib HOG detector."""
        if not self._models_ready:
            h, w = image.shape[:2]

            class _SimRect:
                """Simulated dlib rectangle when dlib is not installed."""

                def __init__(self, left_val, t, r, b):
                    self._left, self._top, self._right, self._bottom = left_val, t, r, b

                def left(self):
                    return self._left

                def top(self):
                    return self._top

                def right(self):
                    return self._right

                def bottom(self):
                    return self._bottom

            return [_SimRect(int(w * 0.25), int(h * 0.25), int(w * 0.75), int(h * 0.75))]

        return _face_detector(image, 1)

    def _get_encoding(self, image: np.ndarray, face_rect) -> np.ndarray:
        """Extract 128-d face encoding from detected face region."""
        if not self._models_ready:
            rng = np.random.RandomState(42)
            return rng.randn(128).astype(np.float64)

        shape = _shape_predictor(image, face_rect)
        encoding = _face_recognizer.compute_face_descriptor(image, shape)
        return np.array(encoding)

    def _assess_quality(self, image: np.ndarray, face_rect) -> float:
        """Assess image quality for enrollment (brightness, sharpness, centering)."""
        import cv2

        h, w = image.shape[:2]

        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        brightness = np.mean(gray) / 255.0

        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness = min(laplacian_var / 500.0, 1.0)

        cx = (face_rect.left() + face_rect.right()) / 2.0
        cy = (face_rect.top() + face_rect.bottom()) / 2.0
        center_dist = np.sqrt(((cx - w / 2) / w) ** 2 + ((cy - h / 2) / h) ** 2)
        centering = max(0, 1.0 - center_dist * 2)

        face_w = face_rect.right() - face_rect.left()
        face_ratio = face_w / w
        size_score = min(face_ratio / 0.3, 1.0)

        quality = 0.25 * brightness + 0.30 * sharpness + 0.25 * centering + 0.20 * size_score
        return round(max(0.0, min(1.0, quality)), 3)

    def _sync_enroll_face(self, image_b64: str, angle: str, user_id: str, salt_b64: str) -> Tuple[str, str, float]:
        """Synchronous face enrollment (runs in thread pool)."""
        if angle not in VALID_ANGLES:
            raise ValueError(f"Invalid angle: {angle}. Must be one of {VALID_ANGLES}")

        try:
            image = self._decode_image(image_b64)
        except Exception:
            raise ValueError("Invalid image data")

        faces = self._detect_faces(image)
        if len(faces) == 0:
            raise ValueError("No face detected in the image")
        if len(faces) > 1:
            raise ValueError("Multiple faces detected. Please ensure only one face is visible")

        face_rect = faces[0]
        quality = self._assess_quality(image, face_rect)

        if quality < 0.3:
            raise ValueError(f"Image quality too low ({quality:.2f}). " "Ensure good lighting and face centering.")

        encoding = self._get_encoding(image, face_rect)
        encoding_bytes = encoding.tobytes()

        encrypted_b64, nonce_b64 = encryption_service.encrypt(encoding_bytes, user_id, salt_b64)

        return encrypted_b64, nonce_b64, quality

    async def enroll_face(self, image_b64: str, angle: str, user_id: str, salt_b64: str) -> Tuple[str, str, float]:
        """
        Process a face image for enrollment.
        Runs CPU-bound work in thread pool to avoid blocking the event loop.

        Returns:
            Tuple of (encrypted_encoding_b64, nonce_b64, quality_score)
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_face_executor, self._sync_enroll_face, image_b64, angle, user_id, salt_b64)

    def _sync_verify_face(
        self,
        frames_b64: List[str],
        stored_encodings: List[dict],
        user_id: str,
        salt_b64: str,
        threshold: float,
    ) -> Tuple[bool, float, int]:
        """Synchronous face verification (runs in thread pool)."""
        stored_vectors = []
        for enc in stored_encodings:
            decrypted = encryption_service.decrypt(
                enc["encoding_blob"],
                enc["encoding_nonce"],
                user_id,
                salt_b64,
            )
            vector = np.frombuffer(decrypted, dtype=np.float64)
            stored_vectors.append(vector)

        if not stored_vectors:
            return False, 0.0, 0

        # Stack stored vectors for vectorized distance computation
        stored_matrix = np.stack(stored_vectors)

        consecutive_matches = 0
        best_confidence = 0.0
        total_frames_matched = 0

        for frame_b64 in frames_b64:
            try:
                image = self._decode_image(frame_b64)
                faces = self._detect_faces(image)
                if len(faces) != 1:
                    consecutive_matches = 0
                    continue

                probe_encoding = self._get_encoding(image, faces[0])

                # Vectorized: compute distances to all stored vectors at once
                distances = np.linalg.norm(stored_matrix - probe_encoding, axis=1)
                min_distance = float(np.min(distances))

                confidence = max(0.0, 1.0 - min_distance)
                confidence = round(min(1.0, confidence), 4)

                if min_distance < threshold:
                    consecutive_matches += 1
                    total_frames_matched += 1
                    best_confidence = max(best_confidence, confidence)
                else:
                    consecutive_matches = 0

                if consecutive_matches >= settings.FACE_MULTI_FRAME_COUNT:
                    return True, best_confidence, total_frames_matched

            except Exception as e:
                logger.warning(f"Frame processing error: {e}")
                consecutive_matches = 0
                continue

        return False, best_confidence, total_frames_matched

    async def verify_face(
        self,
        frames_b64: List[str],
        stored_encodings: List[dict],
        user_id: str,
        salt_b64: str,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, float, int]:
        """
        Verify face identity across multiple frames.
        Runs CPU-bound work in thread pool to avoid blocking the event loop.

        Returns:
            Tuple of (is_match, confidence_score, frames_matched)
        """
        if threshold is None:
            threshold = settings.FACE_MATCH_THRESHOLD

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _face_executor,
            self._sync_verify_face,
            frames_b64,
            stored_encodings,
            user_id,
            salt_b64,
            threshold,
        )


face_service = FaceService()
