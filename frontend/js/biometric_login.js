/**
 * FaceVoiceAuth — Biometric Login Module (Face + Voice combined)
 * Runs both verification pipelines simultaneously.
 */

const BiometricLogin = {
    isVerifying: false,

    async init() {
        await CameraModule.init('#bio-video', '#bio-canvas');
        await MicrophoneModule.init('#bio-waveform');
    },

    async verify() {
        if (this.isVerifying) return;

        const email = $('#bio-login-email')?.value.trim();
        if (!email) {
            showToast('Please enter your email', 'warning');
            return;
        }

        this.isVerifying = true;
        const verifyBtn = $('#bio-verify-btn');
        if (verifyBtn) {
            verifyBtn.disabled = true;
            verifyBtn.innerHTML = '<span class="spinner spinner-sm"></span> Capturing biometrics...';
        }

        this.updatePipeline([
            { label: 'Face Capture', icon: '👁', state: 'active' },
            { label: 'Voice Capture', icon: '🎤', state: 'active' },
            { label: 'Fusion', icon: '🔗', state: '' },
            { label: 'Result', icon: '✓', state: '' },
        ]);

        MicrophoneModule.startRecording();
        CameraModule.showLivenessPrompt('Look at the camera and speak your secret phrase clearly...');

        await new Promise(r => setTimeout(r, 1500));
        const frames = await CameraModule.captureMultipleFrames(3, 400);

        await new Promise(r => setTimeout(r, 2000));
        const audioBase64 = await MicrophoneModule.stopRecording();

        this.updatePipeline([
            { label: 'Face Capture', icon: '👁', state: 'complete' },
            { label: 'Voice Capture', icon: '🎤', state: 'complete' },
            { label: 'Fusion', icon: '🔗', state: 'active' },
            { label: 'Result', icon: '✓', state: '' },
        ]);

        if (verifyBtn) {
            verifyBtn.innerHTML = '<span class="spinner spinner-sm"></span> Verifying...';
        }

        try {
            const result = await apiRequest(`/api/biometric/login?email=${encodeURIComponent(email)}`, {
                method: 'POST',
                body: JSON.stringify({
                    face_frames: frames,
                    voice_audio_base64: audioBase64,
                }),
            });

            if (result.face_confidence !== null) {
                renderConfidence('#bio-face-confidence', result.face_confidence);
            }
            if (result.voice_confidence !== null) {
                renderConfidence('#bio-voice-confidence', result.voice_confidence);
            }
            if (result.fusion_score !== null) {
                renderConfidence('#bio-fusion-score', result.fusion_score);
            }

            if (result.authenticated) {
                this.updatePipeline([
                    { label: 'Face', icon: '👁', state: 'complete' },
                    { label: 'Voice', icon: '🎤', state: 'complete' },
                    { label: 'Fusion', icon: '🔗', state: 'complete' },
                    { label: 'Authenticated', icon: '✓', state: 'complete' },
                ]);

                TokenStore.set(result.access_token);
                showToast('Biometric authentication successful!', 'success');
                setTimeout(() => { window.location.href = '/dashboard.html'; }, 1500);
            } else {
                this.updatePipeline([
                    { label: 'Face', icon: '👁', state: result.face_passed ? 'complete' : 'failed' },
                    { label: 'Voice', icon: '🎤', state: result.voice_passed ? 'complete' : 'failed' },
                    { label: 'Fusion', icon: '🔗', state: 'failed' },
                    { label: 'Failed', icon: '✕', state: 'failed' },
                ]);
                showToast(result.message || 'Authentication failed', 'error');
            }
        } catch (error) {
            this.updatePipeline([
                { label: 'Face', icon: '👁', state: 'failed' },
                { label: 'Voice', icon: '🎤', state: 'failed' },
                { label: 'Fusion', icon: '🔗', state: 'failed' },
                { label: 'Error', icon: '✕', state: 'failed' },
            ]);
            showToast(error.message, 'error');
        } finally {
            this.isVerifying = false;
            if (verifyBtn) { verifyBtn.disabled = false; verifyBtn.innerHTML = '🔐 Verify Identity'; }
        }
    },

    updatePipeline(stages) {
        renderAuthPipeline('#bio-auth-pipeline', stages);
    },

    stop() {
        CameraModule.stop();
        MicrophoneModule.stop();
    }
};
