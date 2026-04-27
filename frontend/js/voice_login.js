/**
 * FaceVoiceAuth — Voice Login Module
 * Voice-based authentication with challenge-response liveness verification.
 */

const VoiceLogin = {
    isVerifying: false,

    async init() {
        const ok = await MicrophoneModule.init('#voice-login-waveform', '#voice-login-timer');
        if (!ok) return;
    },

    async verify() {
        if (this.isVerifying) return;

        const email = $('#voice-login-email')?.value.trim();
        if (!email) {
            showToast('Please enter your email', 'warning');
            return;
        }

        this.isVerifying = true;
        const verifyBtn = $('#voice-verify-btn');
        if (verifyBtn) {
            verifyBtn.disabled = true;
            verifyBtn.innerHTML = '<span class="recording-dot"></span> Recording... Speak now!';
        }

        MicrophoneModule.startRecording();

        setTimeout(async () => {
            const audioBase64 = await MicrophoneModule.stopRecording();

            if (verifyBtn) {
                verifyBtn.innerHTML = '<span class="spinner spinner-sm"></span> Verifying...';
            }

            if (!audioBase64) {
                showToast('Recording failed', 'error');
                this.isVerifying = false;
                if (verifyBtn) { verifyBtn.disabled = false; verifyBtn.innerHTML = '🎤 Verify Voice'; }
                return;
            }

            try {
                const result = await apiRequest(`/api/voice/verify`, {
                    method: 'POST',
                    body: JSON.stringify({ email, audio_base64: audioBase64 })
                });

                renderConfidence('#voice-confidence-meter', result.confidence);

                if (result.authenticated) {
                    showToast(`Voice authenticated! Confidence: ${Math.round(result.confidence * 100)}%`, 'success');
                } else {
                    showToast('Voice not recognized', 'error');
                }
            } catch (error) {
                showToast(error.message, 'error');
            } finally {
                this.isVerifying = false;
                if (verifyBtn) { verifyBtn.disabled = false; verifyBtn.innerHTML = '🎤 Verify Voice'; }
            }
        }, 5000);
    },

    stop() {
        MicrophoneModule.stop();
    }
};
