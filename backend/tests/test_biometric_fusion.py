"""
Test suite for biometric fusion — score-level fusion, fallback logic, thresholds.
"""

import pytest
from backend.services.biometric_fusion_service import biometric_fusion_service


@pytest.mark.asyncio
async def test_fusion_both_pass():
    """Both biometrics above threshold produces authenticated result."""
    auth, score, reason, details = biometric_fusion_service.evaluate_fusion(
        face_confidence=0.90,
        voice_confidence=0.88,
        fallback_allowed=False,
        face_available=True,
        voice_available=True,
    )
    assert auth is True
    assert score >= 0.80
    assert details["decision"] == "accepted"


@pytest.mark.asyncio
async def test_fusion_face_below_minimum():
    """Face below individual minimum causes rejection."""
    auth, score, reason, details = biometric_fusion_service.evaluate_fusion(
        face_confidence=0.40,
        voice_confidence=0.95,
        fallback_allowed=False,
        face_available=True,
        voice_available=True,
    )
    assert auth is False
    assert "face" in reason.lower()
    assert details["decision"] == "rejected_face"


@pytest.mark.asyncio
async def test_fusion_voice_below_minimum():
    """Voice below individual minimum causes rejection."""
    auth, score, reason, details = biometric_fusion_service.evaluate_fusion(
        face_confidence=0.85,
        voice_confidence=0.30,
        fallback_allowed=False,
        face_available=True,
        voice_available=True,
    )
    assert auth is False
    assert "voice" in reason.lower()


@pytest.mark.asyncio
async def test_fusion_fallback_face_only():
    """When voice is unavailable and fallback allowed, face-only works."""
    auth, score, reason, details = biometric_fusion_service.evaluate_fusion(
        face_confidence=0.85,
        voice_confidence=None,
        fallback_allowed=True,
        face_available=True,
        voice_available=False,
    )
    assert auth is True
    assert details["fallback_mode"] == "face_only"


@pytest.mark.asyncio
async def test_fusion_no_fallback_rejected():
    """When voice unavailable and no fallback, authentication fails."""
    auth, score, reason, details = biometric_fusion_service.evaluate_fusion(
        face_confidence=0.90,
        voice_confidence=None,
        fallback_allowed=False,
        face_available=True,
        voice_available=False,
    )
    assert auth is False
    assert "fallback" in reason.lower()


@pytest.mark.asyncio
async def test_fusion_both_unavailable():
    """When both biometrics unavailable, authentication fails."""
    auth, score, reason, details = biometric_fusion_service.evaluate_fusion(
        face_confidence=None,
        voice_confidence=None,
        fallback_allowed=True,
        face_available=False,
        voice_available=False,
    )
    assert auth is False


@pytest.mark.asyncio
async def test_fusion_score_calculation():
    """Fusion score is correctly computed with default weights (0.6/0.4)."""
    score, breakdown = biometric_fusion_service.compute_fusion_score(
        face_confidence=0.90,
        voice_confidence=0.80,
    )
    expected = 0.6 * 0.90 + 0.4 * 0.80
    assert abs(score - expected) < 0.01
    assert breakdown["face_weight"] == 0.6
    assert breakdown["voice_weight"] == 0.4


@pytest.mark.asyncio
async def test_fusion_custom_weights():
    """Custom fusion weights are applied correctly."""
    score, breakdown = biometric_fusion_service.compute_fusion_score(
        face_confidence=0.80,
        voice_confidence=0.90,
        face_weight=0.3,
        voice_weight=0.7,
    )
    expected = 0.3 * 0.80 + 0.7 * 0.90
    assert abs(score - expected) < 0.01
