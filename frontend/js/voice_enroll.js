/**
 * FaceVoiceAuth — Voice Enrollment Module
 * Multi-sample voice capture with quality feedback.
 */

const VoiceEnroll = {
    sessionId: null,
    challengePin: '',
    sampleCount: 0,
    minSamples: 3,
    maxSamples: 10,
    isRecording: false,

    async start() {
        const ok = await MicrophoneModule.init('#voice-enroll-waveform', '#voice-enroll-timer');
        if (!ok) return;

        try {
            const result = await apiRequest('/api/voice/enroll/start', { method: 'POST' });
            this.sessionId = result.session_id;
            this.challengePin = result.challenge_pin;
            this.minSamples = result.min_samples;
            this.maxSamples = result.max_samples;

            const pinEl = $('#voice-challenge-pin');
            if (pinEl) pinEl.textContent = this.challengePin;

            const instructionEl = $('#voice-instruction');
            if (instructionEl) instructionEl.textContent = result.instructions;

            showToast('Voice enrollment started. Speak the PIN shown on screen.', 'info');
            this.updateSampleProgress();
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async recordSample() {
        if (this.isRecording || this.sampleCount >= this.maxSamples) return;

        this.isRecording = true;
        const recordBtn = $('#voice-record-btn');
        if (recordBtn) {
            recordBtn.innerHTML = '<span class="recording-dot"></span> Recording... (speak now)';
            recordBtn.classList.add('btn-danger');
        }

        MicrophoneModule.startRecording();

        setTimeout(async () => {
            const audioBase64 = await MicrophoneModule.stopRecording();
            this.isRecording = false;

            if (recordBtn) {
                recordBtn.innerHTML = '🎤 Record Sample';
                recordBtn.classList.remove('btn-danger');
            }

            if (!audioBase64) {
                showToast('Recording failed', 'error');
                return;
            }

            try {
                const result = await apiRequest(`/api/voice/enroll/sample`, {
                    method: 'POST',
                    body: JSON.stringify({ session_id: this.sessionId, audio_base64: audioBase64 })
                });

                if (result.is_acceptable) {
                    this.sampleCount = result.total_samples;
                    showToast(`Sample ${this.sampleCount} accepted (quality: ${Math.round(result.quality_score * 100)}%)`, 'success');
                } else {
                    showToast(`Sample rejected: ${result.feedback.join('. ')}`, 'warning');
                }

                this.updateSampleProgress();
            } catch (error) {
                showToast(error.message, 'error');
            }
        }, 5000);
    },

    updateSampleProgress() {
        const progressEl = $('#voice-sample-progress');
        if (!progressEl) return;

        const percent = Math.round((this.sampleCount / this.minSamples) * 100);
        progressEl.innerHTML = `
            <div class="progress" style="margin-bottom: 0.5rem;">
                <div class="progress-bar progress-purple" style="width: ${Math.min(percent, 100)}%;"></div>
            </div>
            <span style="font-size: 0.85rem; color: var(--text-secondary);">
                ${this.sampleCount} / ${this.minSamples} samples (${this.sampleCount >= this.minSamples ? 'ready to complete' : `${this.minSamples - this.sampleCount} more needed`})
            </span>
        `;

        const completeBtn = $('#voice-complete-btn');
        if (completeBtn) {
            completeBtn.disabled = this.sampleCount < this.minSamples;
        }
    },

    async complete() {
        if (this.sampleCount < this.minSamples) {
            showToast(`Need at least ${this.minSamples} samples`, 'warning');
            return;
        }

        try {
            const result = await apiRequest(`/api/voice/enroll/complete?session_id=${this.sessionId}`, {
                method: 'POST',
            });

            showToast(result.message, 'success');
            MicrophoneModule.stop();
            return true;
        } catch (error) {
            showToast(error.message, 'error');
            return false;
        }
    },

    stop() {
        MicrophoneModule.stop();
    }
};
