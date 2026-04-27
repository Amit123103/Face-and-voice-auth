/**
 * FaceVoiceAuth — Face Enrollment Module
 * Multi-angle face capture with progress tracking.
 */

const FaceEnroll = {
    angles: ['front', 'left_30', 'right_30', 'up_15', 'down_15'],
    angleLabels: { front: 'Front', left_30: 'Left 30°', right_30: 'Right 30°', up_15: 'Up 15°', down_15: 'Down 15°' },
    enrolled: [],
    currentAngle: 0,
    isProcessing: false,

    async init() {
        const ok = await CameraModule.init('#face-enroll-video', '#face-enroll-canvas');
        if (!ok) return;
        this.updateProgress();
        this.showAngleInstruction();
    },

    updateProgress() {
        const container = $('#face-enroll-progress');
        if (!container) return;
        container.innerHTML = this.angles.map((angle, i) => {
            let cls = '';
            if (this.enrolled.includes(angle)) cls = 'completed';
            else if (i === this.currentAngle) cls = 'active';
            const icon = this.enrolled.includes(angle) ? '✓' : (i + 1);
            return `<div class="enrollment-step">
                <div class="step-circle ${cls}">${icon}</div>
                <span class="step-label">${this.angleLabels[angle]}</span>
            </div>`;
        }).join('');
    },

    showAngleInstruction() {
        if (this.currentAngle >= this.angles.length) {
            CameraModule.showLivenessPrompt('All angles captured!');
            return;
        }
        const angle = this.angles[this.currentAngle];
        const instructions = {
            front: 'Look straight at the camera',
            left_30: 'Turn your head slightly to the LEFT',
            right_30: 'Turn your head slightly to the RIGHT',
            up_15: 'Tilt your head slightly UP',
            down_15: 'Tilt your head slightly DOWN',
        };
        CameraModule.showLivenessPrompt(instructions[angle]);
    },

    async captureAngle() {
        if (this.isProcessing) return;
        this.isProcessing = true;

        const angle = this.angles[this.currentAngle];
        const captureBtn = $('#face-capture-btn');
        if (captureBtn) {
            captureBtn.disabled = true;
            captureBtn.innerHTML = '<span class="spinner spinner-sm"></span> Processing...';
        }

        const quality = CameraModule.checkQuality();
        if (!quality.ok) {
            showToast(quality.issues.join('. '), 'warning');
            this.isProcessing = false;
            if (captureBtn) { captureBtn.disabled = false; captureBtn.innerHTML = '📸 Capture'; }
            return;
        }

        const frame = CameraModule.captureFrame();
        if (!frame) {
            showToast('Failed to capture frame', 'error');
            this.isProcessing = false;
            if (captureBtn) { captureBtn.disabled = false; captureBtn.innerHTML = '📸 Capture'; }
            return;
        }

        try {
            const result = await apiRequest('/api/face/enroll', {
                method: 'POST',
                body: JSON.stringify({ angle, image_base64: frame }),
            });

            this.enrolled.push(angle);
            showToast(`${this.angleLabels[angle]} captured (quality: ${Math.round(result.quality_score * 100)}%)`, 'success');

            this.currentAngle++;
            this.updateProgress();
            this.showAngleInstruction();

            if (result.enrollment_complete) {
                showToast('Face enrollment complete!', 'success');
            }
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            this.isProcessing = false;
            if (captureBtn) { captureBtn.disabled = false; captureBtn.innerHTML = '📸 Capture'; }
        }
    },

    stop() {
        CameraModule.stop();
    }
};
