"""
Biometric Fusion Service — score-level fusion for combined face+voice authentication.
Weighted combination with configurable thresholds and fallback logic.
"""

import logging
from typing import Optional, Tuple

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class BiometricFusionService:
    """Implements weighted score fusion for multi-modal biometric authentication."""

    def compute_fusion_score(
        self,
        face_confidence: Optional[float],
        voice_confidence: Optional[float],
        face_weight: Optional[float] = None,
        voice_weight: Optional[float] = None,
    ) -> Tuple[float, dict]:
        """
        Compute the fused biometric score from face and voice confidences.

        Returns:
            Tuple of (fusion_score, breakdown_dict)
        """
        fw = face_weight if face_weight is not None else settings.FACE_FUSION_WEIGHT
        vw = voice_weight if voice_weight is not None else settings.VOICE_FUSION_WEIGHT

        total_weight = fw + vw
        if total_weight == 0:
            return 0.0, {"error": "Both weights are zero"}
        fw_norm = fw / total_weight
        vw_norm = vw / total_weight

        fc = face_confidence if face_confidence is not None else 0.0
        vc = voice_confidence if voice_confidence is not None else 0.0

        fusion = (fw_norm * fc) + (vw_norm * vc)
        fusion = round(max(0.0, min(1.0, fusion)), 4)

        breakdown = {
            "face_confidence": round(fc, 4),
            "voice_confidence": round(vc, 4),
            "face_weight": round(fw_norm, 3),
            "voice_weight": round(vw_norm, 3),
            "fusion_score": fusion,
        }

        return fusion, breakdown

    def evaluate_fusion(
        self,
        face_confidence: Optional[float],
        voice_confidence: Optional[float],
        fallback_allowed: bool = False,
        face_available: bool = True,
        voice_available: bool = True,
    ) -> Tuple[bool, float, str, dict]:
        """
        Evaluate combined biometric authentication result.

        Returns:
            Tuple of (authenticated, fusion_score, decision_reason, audit_details)
        """
        fc = face_confidence if face_confidence is not None else 0.0
        vc = voice_confidence if voice_confidence is not None else 0.0

        if not face_available and not voice_available:
            return False, 0.0, "Both biometric inputs unavailable", {
                "face_available": False,
                "voice_available": False,
                "decision": "rejected",
            }

        if not face_available or not voice_available:
            if not fallback_allowed:
                missing = "camera" if not face_available else "microphone"
                return False, 0.0, (
                    f"Single-modal fallback not allowed. {missing} input missing."
                ), {
                    "face_available": face_available,
                    "voice_available": voice_available,
                    "fallback_allowed": False,
                    "decision": "rejected_no_fallback",
                }

            if face_available and not voice_available:
                passed = fc >= settings.FUSION_INDIVIDUAL_MIN
                return passed, fc, (
                    "Voice unavailable, single-modal face fallback"
                ), {
                    "face_available": True,
                    "voice_available": False,
                    "fallback_mode": "face_only",
                    "face_confidence": round(fc, 4),
                    "decision": "accepted_fallback" if passed else "rejected_fallback",
                }

            if voice_available and not face_available:
                passed = vc >= settings.FUSION_INDIVIDUAL_MIN
                return passed, vc, (
                    "Face unavailable, single-modal voice fallback"
                ), {
                    "face_available": False,
                    "voice_available": True,
                    "fallback_mode": "voice_only",
                    "voice_confidence": round(vc, 4),
                    "decision": "accepted_fallback" if passed else "rejected_fallback",
                }

        fusion_score, breakdown = self.compute_fusion_score(fc, vc)

        face_passes = fc >= settings.FUSION_INDIVIDUAL_MIN
        voice_passes = vc >= settings.FUSION_INDIVIDUAL_MIN
        fusion_passes = fusion_score >= settings.FUSION_MIN_SCORE

        authenticated = fusion_passes and face_passes and voice_passes

        if authenticated:
            reason = "Combined biometric authentication successful"
            decision = "accepted"
        elif not face_passes:
            reason = f"Face confidence {fc:.3f} below minimum {settings.FUSION_INDIVIDUAL_MIN}"
            decision = "rejected_face"
        elif not voice_passes:
            reason = f"Voice confidence {vc:.3f} below minimum {settings.FUSION_INDIVIDUAL_MIN}"
            decision = "rejected_voice"
        else:
            reason = f"Fusion score {fusion_score:.3f} below minimum {settings.FUSION_MIN_SCORE}"
            decision = "rejected_fusion"

        audit_details = {
            **breakdown,
            "face_passes_individual": face_passes,
            "voice_passes_individual": voice_passes,
            "fusion_passes": fusion_passes,
            "min_individual": settings.FUSION_INDIVIDUAL_MIN,
            "min_fusion": settings.FUSION_MIN_SCORE,
            "decision": decision,
            "reason": reason,
        }

        logger.info(
            f"Biometric fusion: score={fusion_score:.3f}, "
            f"face={fc:.3f}, voice={vc:.3f}, "
            f"decision={decision}"
        )

        return authenticated, fusion_score, reason, audit_details


biometric_fusion_service = BiometricFusionService()
