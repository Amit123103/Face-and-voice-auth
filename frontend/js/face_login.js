/**
 * FaceVoiceAuth — Face Login Module
 * Multi-frame face verification with auth pipeline visualization.
 */

const FaceLogin = {
    isVerifying: false,

    async init() {
        const ok = await CameraModule.init('#face-login-video', '#face-login-canvas');
        if (!ok) return;
        this.updatePipeline('ready');
    },

    updatePipeline(state) {
        const container = $('#face-auth-pipeline');
        if (!container) return;
        const stages = [
            { label: 'Detecting', icon: '👁', state: state === 'detecting' ? 'active' : (state === 'ready' ? '' : 'complete') },
            { label: 'Liveness', icon: '🔒', state: state === 'liveness' ? 'active' : (['detecting', 'ready'].includes(state) ? '' : 'complete') },
            { label: 'Matching', icon: '🔍', state: state === 'matching' ? 'active' : (['detecting', 'ready', 'liveness'].includes(state) ? '' : 'complete') },
            { label: 'Result', icon: '✓', state: state === 'success' ? 'complete' : (state === 'failed' ? 'failed' : '') },
        ];
        renderAuthPipeline(container, stages);
    },

    async verify() {
        if (this.isVerifying) return;
        this.isVerifying = true;

        const email = $('#face-login-email')?.value.trim();
        if (!email) {
            showToast('Please enter your email', 'warning');
            this.isVerifying = false;
            return;
        }

        const verifyBtn = $('#face-verify-btn');
        if (verifyBtn) {
            verifyBtn.disabled = true;
            verifyBtn.innerHTML = '<span class="spinner spinner-sm"></span> Verifying...';
        }

        this.updatePipeline('detecting');
        CameraModule.showLivenessPrompt('Hold still — detecting face...');
        await new Promise(r => setTimeout(r, 800));

        this.updatePipeline('liveness');
        CameraModule.showLivenessPrompt('Please blink naturally');
        await new Promise(r => setTimeout(r, 1500));

        this.updatePipeline('matching');
        CameraModule.showLivenessPrompt('Matching identity...');
        const frames = await CameraModule.captureMultipleFrames(3, 400);

        try {
            const result = await apiRequest(`/api/face/verify?email=${encodeURIComponent(email)}`, {
                method: 'POST',
                body: JSON.stringify({ frames }),
            });

            renderConfidence('#face-confidence-meter', result.confidence);

            if (result.authenticated) {
                this.updatePipeline('success');
                CameraModule.showLivenessPrompt('✓ Identity Confirmed');
                showToast(`Face authenticated! Confidence: ${Math.round(result.confidence * 100)}%`, 'success');
            } else {
                this.updatePipeline('failed');
                CameraModule.showLivenessPrompt('✕ Identity Not Matched');
                showToast('Face not recognized', 'error');
            }
        } catch (error) {
            this.updatePipeline('failed');
            showToast(error.message, 'error');
        } finally {
            this.isVerifying = false;
            if (verifyBtn) { verifyBtn.disabled = false; verifyBtn.innerHTML = '🔍 Verify Face'; }
        }
    },

    stop() {
        CameraModule.stop();
    }
};
