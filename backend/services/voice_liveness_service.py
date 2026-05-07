"""
Voice Liveness Detection Service — anti-spoofing for voice authentication.
Detects playback attacks, silence abuse, and uses challenge-response verification.
"""

import base64
import io
import logging
import struct
import wave
from typing import Optional, Tuple

import numpy as np

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

REPLAY_LPF_CUTOFF_HZ = 8000
SILENCE_THRESHOLD = 0.01
MAX_SILENCE_RATIO = 0.60


class VoiceLivenessService:
    """Detects voice spoofing attacks including replay and synthesis."""

    def _decode_wav_to_samples(self, audio_b64: str) -> Tuple[np.ndarray, int]:
        """Decode base64 WAV to float32 samples and sample rate."""
        audio_bytes = base64.b64decode(audio_b64)
        buffer = io.BytesIO(audio_bytes)

        with wave.open(buffer, "rb") as wav:
            sample_rate = wav.getframerate()
            n_channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            n_frames = wav.getnframes()
            raw = wav.readframes(n_frames)

        if sampwidth == 2:
            fmt = f"<{n_frames * n_channels}h"
            samples = np.array(struct.unpack(fmt, raw), dtype=np.float32)
            samples /= 32768.0
        else:
            fmt = f"<{n_frames * n_channels}i"
            samples = np.array(struct.unpack(fmt, raw), dtype=np.float32)
            samples /= 2147483648.0

        if n_channels > 1:
            samples = samples.reshape(-1, n_channels).mean(axis=1)

        return samples, sample_rate

    def detect_replay_attack(self, samples: np.ndarray, sample_rate: int) -> Tuple[bool, float]:
        """
        Detect replay attacks by analyzing frequency spectrum.
        Loudspeaker replays typically show energy cutoff around 8kHz.

        Returns:
            Tuple of (is_live, confidence)
        """
        n = len(samples)
        if n < 1024:
            return False, 0.0

        fft = np.fft.rfft(samples)
        magnitude = np.abs(fft)
        freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)

        cutoff_idx = np.searchsorted(freqs, REPLAY_LPF_CUTOFF_HZ)
        total_idx = len(magnitude)

        if cutoff_idx >= total_idx - 1:
            return True, 0.8

        energy_below = np.sum(magnitude[:cutoff_idx] ** 2)
        energy_above = np.sum(magnitude[cutoff_idx:] ** 2)
        total_energy = energy_below + energy_above

        if total_energy == 0:
            return False, 0.0

        high_freq_ratio = energy_above / total_energy

        is_live = high_freq_ratio > 0.05
        confidence = min(high_freq_ratio / 0.15, 1.0)

        return is_live, round(confidence, 3)

    def check_silence_ratio(self, samples: np.ndarray) -> Tuple[bool, float]:
        """
        Reject clips with excessive silence.

        Returns:
            Tuple of (acceptable, silence_ratio)
        """
        frame_size = 512
        total_frames = max(1, len(samples) // frame_size)
        silent_frames = 0

        for i in range(total_frames):
            frame = samples[i * frame_size:(i + 1) * frame_size]
            if np.max(np.abs(frame)) < SILENCE_THRESHOLD:
                silent_frames += 1

        ratio = silent_frames / total_frames
        return ratio <= MAX_SILENCE_RATIO, round(ratio, 3)

    def validate_audio_format(self, audio_b64: str) -> Tuple[bool, dict]:
        """
        Validate audio format requirements.

        Returns:
            Tuple of (is_valid, info_dict)
        """
        try:
            audio_bytes = base64.b64decode(audio_b64)
            buffer = io.BytesIO(audio_bytes)
            with wave.open(buffer, "rb") as wav:
                info = {
                    "sample_rate": wav.getframerate(),
                    "channels": wav.getnchannels(),
                    "sample_width": wav.getsampwidth(),
                    "duration": wav.getnframes() / wav.getframerate(),
                }
        except Exception:
            return False, {"error": "Invalid WAV format"}

        issues = []
        if info["sample_rate"] < 16000:
            issues.append(f"Sample rate {info['sample_rate']}Hz below 16000Hz minimum")
        if info["duration"] < settings.VOICE_MIN_DURATION:
            issues.append(f"Duration {info['duration']:.1f}s below {settings.VOICE_MIN_DURATION}s minimum")
        if info["duration"] > settings.VOICE_MAX_DURATION:
            issues.append(f"Duration {info['duration']:.1f}s above {settings.VOICE_MAX_DURATION}s maximum")

        info["issues"] = issues
        return len(issues) == 0, info

    async def verify_challenge_response(self, audio_b64: str, expected_pin: str) -> Tuple[bool, str]:
        """
        Verify that the user spoke the correct challenge PIN using Whisper STT.

        Returns:
            Tuple of (matched, transcribed_text)
        """
        try:
            import whisper

            samples_bytes = base64.b64decode(audio_b64)
            buffer = io.BytesIO(samples_bytes)

            with wave.open(buffer, "rb") as wav:
                sample_rate = wav.getframerate()
                n_frames = wav.getnframes()
                raw = wav.readframes(n_frames)

            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            if sample_rate != 16000:
                from scipy import signal as scipy_signal

                num_samples = int(len(samples) * 16000 / sample_rate)
                samples = scipy_signal.resample(samples, num_samples)

            model = whisper.load_model("tiny")
            result = model.transcribe(samples, language="en")
            transcribed = result["text"].strip()

            digits_map = {
                "zero": "0",
                "one": "1",
                "two": "2",
                "three": "3",
                "four": "4",
                "five": "5",
                "six": "6",
                "seven": "7",
                "eight": "8",
                "nine": "9",
            }

            cleaned = transcribed.lower()
            for word, digit in digits_map.items():
                cleaned = cleaned.replace(word, digit)
            cleaned = "".join(c for c in cleaned if c.isdigit())

            distance = self._edit_distance(cleaned, expected_pin)
            matched = distance <= 1

            return matched, transcribed

        except ImportError:
            logger.warning("Whisper not available, skipping challenge verification")
            return True, "[whisper_unavailable]"
        except Exception as e:
            logger.error(f"Challenge verification error: {e}")
            return False, ""

    def _edit_distance(self, s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance between two strings."""
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,
                    dp[i][j - 1] + 1,
                    dp[i - 1][j - 1] + cost,
                )
        return dp[m][n]

    async def evaluate_liveness(
        self,
        audio_b64: str,
        challenge_pin: Optional[str] = None,
    ) -> Tuple[bool, float, dict]:
        """
        Run full voice liveness evaluation.

        Returns:
            Tuple of (passed, overall_score, details)
        """
        format_valid, format_info = self.validate_audio_format(audio_b64)
        if not format_valid:
            return False, 0.0, {"error": "Invalid audio format", "details": format_info}

        samples, sample_rate = self._decode_wav_to_samples(audio_b64)

        replay_live, replay_score = self.detect_replay_attack(samples, sample_rate)

        silence_ok, silence_ratio = self.check_silence_ratio(samples)

        if challenge_pin:
            challenge_ok, transcribed = await self.verify_challenge_response(audio_b64, challenge_pin)
        else:
            challenge_ok = True
            transcribed = "[no_challenge]"

        weights = {"replay": 0.35, "silence": 0.25, "challenge": 0.40}
        overall = (
            weights["replay"] * replay_score
            + weights["silence"] * (1.0 if silence_ok else 0.0)
            + weights["challenge"] * (1.0 if challenge_ok else 0.0)
        )
        overall = round(overall, 3)
        passed = overall >= settings.MIN_VOICE_LIVENESS_SCORE

        details = {
            "replay_live": replay_live,
            "replay_score": replay_score,
            "silence_ok": silence_ok,
            "silence_ratio": silence_ratio,
            "challenge_matched": challenge_ok,
            "transcribed": transcribed,
            "overall_score": overall,
            "threshold": settings.MIN_VOICE_LIVENESS_SCORE,
            "passed": passed,
        }

        if not passed:
            logger.warning(f"Voice liveness check failed: {details}")

        return passed, overall, details


voice_liveness_service = VoiceLivenessService()
