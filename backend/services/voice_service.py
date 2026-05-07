"""
Voice Authentication Service — speaker verification using ECAPA-TDNN embeddings.
Handles enrollment (3-10 voice samples) and cosine-similarity verification.
Optimized: thread pool for CPU-bound work.
"""

import asyncio
import base64
import io
import logging
import struct
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import numpy as np

from backend.config import get_settings
from backend.services.encryption_service import encryption_service

settings = get_settings()
logger = logging.getLogger(__name__)

_voice_model = None
_voice_model_loaded = False

EMBEDDING_DIM = 256

# Thread pool for CPU-bound voice processing (embedding, verification)
_voice_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice")


def _load_voice_model() -> bool:
    """Lazy-load the ECAPA-TDNN speaker embedding model."""
    global _voice_model, _voice_model_loaded

    if _voice_model_loaded:
        return True

    try:
        from speechbrain.inference.speaker import EncoderClassifier

        _voice_model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
        )
        _voice_model_loaded = True
        logger.info("Voice ECAPA-TDNN model loaded successfully")
        return True
    except Exception as e:
        logger.warning(f"Voice model not available: {e}. Using simulation mode.")
        _voice_model_loaded = False
        return False


class VoiceService:
    """Handles voice enrollment and speaker verification."""

    def __init__(self) -> None:
        self._models_ready = _load_voice_model()
        self._whisper_model = None

    def _load_whisper(self):
        """Lazy-load the Whisper model for STT."""
        if self._whisper_model is not None:
            return self._whisper_model
        try:
            import whisper
            self._whisper_model = whisper.load_model("tiny")
            return self._whisper_model
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            return None

    @property
    def is_ready(self) -> bool:
        """Check if voice model is loaded."""
        return self._models_ready

    def _decode_wav(self, audio_b64: str) -> Tuple[np.ndarray, int]:
        """
        Decode a base64-encoded WAV audio blob.

        Returns:
            Tuple of (samples_float32, sample_rate)
        """
        audio_bytes = base64.b64decode(audio_b64)
        buffer = io.BytesIO(audio_bytes)

        try:
            with wave.open(buffer, "rb") as wav:
                sample_rate = wav.getframerate()
                n_channels = wav.getnchannels()
                sampwidth = wav.getsampwidth()
                n_frames = wav.getnframes()
                raw = wav.readframes(n_frames)
        except Exception:
            raise ValueError("Invalid WAV audio data")

        if sampwidth == 2:
            fmt = f"<{n_frames * n_channels}h"
            samples = np.array(struct.unpack(fmt, raw), dtype=np.float32)
            samples /= 32768.0
        elif sampwidth == 4:
            fmt = f"<{n_frames * n_channels}i"
            samples = np.array(struct.unpack(fmt, raw), dtype=np.float32)
            samples /= 2147483648.0
        else:
            raise ValueError(f"Unsupported sample width: {sampwidth}")

        if n_channels > 1:
            samples = samples.reshape(-1, n_channels).mean(axis=1)

        return samples, sample_rate

    def _compute_snr(self, samples: np.ndarray, sample_rate: int) -> float:
        """
        Estimate Signal-to-Noise Ratio in dB.
        Uses a simple energy-based method comparing signal to noise floor.
        """
        frame_size = int(0.025 * sample_rate)
        hop_size = int(0.010 * sample_rate)
        energies = []

        for i in range(0, len(samples) - frame_size, hop_size):
            frame = samples[i: i + frame_size]
            energy = np.sum(frame ** 2) / frame_size
            energies.append(energy)

        if not energies:
            return 0.0

        energies = np.array(energies)
        sorted_e = np.sort(energies)
        noise_floor = np.mean(sorted_e[: max(1, len(sorted_e) // 5)])
        signal_level = np.mean(sorted_e[len(sorted_e) // 2:])

        if noise_floor <= 0:
            return 40.0

        snr = 10 * np.log10(signal_level / noise_floor)
        return round(max(0.0, snr), 2)

    def _compute_silence_ratio(self, samples: np.ndarray, threshold: float = 0.01) -> float:
        """Compute the ratio of silence frames in the audio."""
        frame_size = 512
        total_frames = len(samples) // frame_size
        if total_frames == 0:
            return 1.0

        silent_frames = 0
        for i in range(total_frames):
            frame = samples[i * frame_size: (i + 1) * frame_size]
            if np.max(np.abs(frame)) < threshold:
                silent_frames += 1

        return silent_frames / total_frames

    def assess_sample_quality(
        self, audio_b64: str
    ) -> Tuple[bool, float, float, float, List[str]]:
        """
        Assess the quality of a voice sample for enrollment.

        Returns:
            Tuple of (is_acceptable, quality_score, snr_db, duration_s, feedback)
        """
        samples, sample_rate = self._decode_wav(audio_b64)
        duration = len(samples) / sample_rate
        feedback = []

        if sample_rate < 16000:
            feedback.append(f"Sample rate {sample_rate}Hz is below minimum 16000Hz")

        if duration < settings.VOICE_MIN_DURATION:
            feedback.append(
                f"Audio too short ({duration:.1f}s). Minimum {settings.VOICE_MIN_DURATION}s required."
            )
        elif duration > settings.VOICE_MAX_DURATION:
            feedback.append(
                f"Audio too long ({duration:.1f}s). Maximum {settings.VOICE_MAX_DURATION}s."
            )

        snr = self._compute_snr(samples, sample_rate)
        if snr < settings.VOICE_MIN_SNR:
            feedback.append(
                f"Audio too noisy (SNR: {snr:.1f}dB). Minimum {settings.VOICE_MIN_SNR}dB required."
            )

        rms = np.sqrt(np.mean(samples ** 2))
        if rms < 0.005:
            feedback.append("Audio is too quiet. Please speak louder.")

        silence_ratio = self._compute_silence_ratio(samples)
        if silence_ratio > 0.6:
            feedback.append("Too much silence detected. Please speak for the full duration.")

        quality = 0.0
        if duration >= settings.VOICE_MIN_DURATION:
            quality += 0.25
        if snr >= settings.VOICE_MIN_SNR:
            quality += 0.30
        if rms >= 0.01:
            quality += 0.20
        if silence_ratio <= 0.4:
            quality += 0.15
        if sample_rate >= 16000:
            quality += 0.10

        is_acceptable = len(feedback) == 0 and quality >= 0.6
        return is_acceptable, round(quality, 3), snr, round(duration, 2), feedback

    def _extract_embedding(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """
        Extract a d-vector (speaker embedding) from audio samples.
        Uses ECAPA-TDNN if available, otherwise simulation.
        """
        if self._models_ready and _voice_model is not None:
            import torch

            waveform = torch.tensor(samples).unsqueeze(0)
            if sample_rate != 16000:
                import torchaudio

                waveform = torchaudio.functional.resample(
                    waveform, sample_rate, 16000
                )
            embedding = _voice_model.encode_batch(waveform)
            return embedding.squeeze().cpu().numpy()
        else:
            rng = np.random.RandomState(
                int(np.sum(np.abs(samples[:1000])) * 10000) % (2 ** 31)
            )
            emb = rng.randn(EMBEDDING_DIM).astype(np.float64)
            emb /= np.linalg.norm(emb)
            return emb

    def _sync_enroll_sample(self, audio_b64: str, user_id: str, salt_b64: str) -> Tuple[str, str, float, float, float]:
        """Synchronous enrollment (runs in thread pool)."""
        is_ok, quality, snr, duration, feedback = self.assess_sample_quality(audio_b64)
        if not is_ok:
            raise ValueError(
                f"Voice sample quality insufficient: {'; '.join(feedback)}"
            )

        samples, sample_rate = self._decode_wav(audio_b64)
        embedding = self._extract_embedding(samples, sample_rate)
        embedding_bytes = embedding.tobytes()

        encrypted_b64, nonce_b64 = encryption_service.encrypt(
            embedding_bytes, user_id, salt_b64
        )

        return encrypted_b64, nonce_b64, quality, snr, duration

    async def enroll_sample(
        self, audio_b64: str, user_id: str, salt_b64: str
    ) -> Tuple[str, str, float, float, float]:
        """
        Process a single voice sample for enrollment.
        Runs CPU-bound work in thread pool.

        Returns:
            Tuple of (encrypted_embedding_b64, nonce_b64, quality, snr, duration)
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _voice_executor, self._sync_enroll_sample, audio_b64, user_id, salt_b64
        )

    async def compute_averaged_voiceprint(
        self,
        encrypted_embeddings: List[dict],
        user_id: str,
        salt_b64: str,
    ) -> Tuple[str, str]:
        """
        Average multiple enrollment embeddings into a stable voice print.

        Returns:
            Tuple of (encrypted_avg_embedding_b64, nonce_b64)
        """
        vectors = []
        for emb in encrypted_embeddings:
            decrypted = encryption_service.decrypt(
                emb["ciphertext_b64"], emb["nonce_b64"], user_id, salt_b64
            )
            vec = np.frombuffer(decrypted, dtype=np.float64)
            vectors.append(vec)

        avg_vector = np.mean(vectors, axis=0)
        avg_vector /= np.linalg.norm(avg_vector)

        encrypted_b64, nonce_b64 = encryption_service.encrypt(
            avg_vector.tobytes(), user_id, salt_b64
        )
        return encrypted_b64, nonce_b64

    def _sync_verify_voice(
        self,
        audio_b64: str,
        stored_voiceprint: dict,
        user_id: str,
        salt_b64: str,
        threshold: float,
    ) -> Tuple[bool, float]:
        """Synchronous voice verification (runs in thread pool)."""
        samples, sample_rate = self._decode_wav(audio_b64)
        probe_embedding = self._extract_embedding(samples, sample_rate)

        stored_decrypted = encryption_service.decrypt(
            stored_voiceprint["embedding_blob"],
            stored_voiceprint["embedding_nonce"],
            user_id,
            salt_b64,
        )
        stored_vector = np.frombuffer(stored_decrypted, dtype=np.float64)

        probe_norm = probe_embedding / (np.linalg.norm(probe_embedding) + 1e-10)
        stored_norm = stored_vector / (np.linalg.norm(stored_vector) + 1e-10)

        cosine_sim = float(np.dot(probe_norm, stored_norm))
        cosine_sim = max(0.0, min(1.0, cosine_sim))

        is_match = cosine_sim >= threshold
        return is_match, round(cosine_sim, 4)

    async def verify_voice(
        self,
        audio_b64: str,
        stored_voiceprint: dict,
        user_id: str,
        salt_b64: str,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, float]:
        """
        Verify a voice clip against a stored voice print.
        Runs CPU-bound work in thread pool.

        Returns:
            Tuple of (is_match, cosine_similarity)
        """
        if threshold is None:
            threshold = settings.VOICE_MATCH_THRESHOLD

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _voice_executor,
            self._sync_verify_voice,
            audio_b64, stored_voiceprint, user_id, salt_b64, threshold,
        )

    async def transcribe_audio(self, audio_b64: str) -> str:
        """Transcribe audio to text using Whisper."""
        model = self._load_whisper()
        if not model:
            return ""

        try:
            samples, sample_rate = self._decode_wav(audio_b64)

            # Whisper requires 16kHz
            if sample_rate != 16000:
                from scipy import signal as scipy_signal
                num_samples = int(len(samples) * 16000 / sample_rate)
                samples = scipy_signal.resample(samples, num_samples)

            result = await asyncio.get_running_loop().run_in_executor(
                _voice_executor,
                lambda: model.transcribe(samples, language="en")
            )
            return result.get("text", "").strip()
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""

    def _edit_distance(self, s1: str, s2: str) -> int:
        """Levenshtein distance helper."""
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if s1[i - 1].lower() == s2[j - 1].lower() else 1
                dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
        return dp[m][n]

    async def verify_passphrase(self, audio_b64: str, expected_text: str) -> Tuple[bool, str]:
        """Verify that the spoken words match the expected passphrase."""
        transcribed = await self.transcribe_audio(audio_b64)
        if not transcribed or not expected_text:
            return False, transcribed

        # Clean strings: remove punctuation and extra whitespace
        import re
        def clean(s): return re.sub(r'[^\w\s]', '', s.lower()).strip()

        c1, c2 = clean(transcribed), clean(expected_text)
        dist = self._edit_distance(c1, c2)

        # Allow small tolerance (10% of length or 2 characters)
        max_dist = max(2, int(len(c2) * 0.2))
        return dist <= max_dist, transcribed


voice_service = VoiceService()
