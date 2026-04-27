/**
 * FaceVoiceAuth — Microphone Module
 * Audio capture via MediaRecorder, real-time waveform visualization, WAV encoding.
 */

const MicrophoneModule = {
    stream: null,
    mediaRecorder: null,
    audioContext: null,
    analyser: null,
    animFrameId: null,
    chunks: [],
    isRecording: false,
    canvasEl: null,
    canvasCtx: null,
    recordingStartTime: 0,
    timerEl: null,

    async init(canvasSelector, timerSelector) {
        this.canvasEl = typeof canvasSelector === 'string' ? $(canvasSelector) : canvasSelector;
        if (timerSelector) {
            this.timerEl = typeof timerSelector === 'string' ? $(timerSelector) : timerSelector;
        }
        if (this.canvasEl) {
            this.canvasCtx = this.canvasEl.getContext('2d');
        }

        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });

            this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 16000,
            });
            const source = this.audioContext.createMediaStreamSource(this.stream);
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            source.connect(this.analyser);

            this.drawWaveform();
            showToast('Microphone activated', 'success');
            return true;
        } catch (error) {
            let msg = 'Microphone access denied';
            if (error.name === 'NotFoundError') msg = 'No microphone detected';
            else if (error.name === 'NotAllowedError') msg = 'Microphone permission denied';
            showToast(msg, 'error');
            return false;
        }
    },

    drawWaveform() {
        if (!this.analyser || !this.canvasCtx) return;

        const canvas = this.canvasEl;
        const ctx = this.canvasCtx;
        const bufferLength = this.analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const draw = () => {
            this.animFrameId = requestAnimationFrame(draw);
            this.analyser.getByteFrequencyData(dataArray);

            ctx.fillStyle = 'rgba(15, 15, 26, 0.85)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            const barWidth = (canvas.width / bufferLength) * 2.5;
            let x = 0;

            for (let i = 0; i < bufferLength; i++) {
                const barHeight = (dataArray[i] / 255) * canvas.height * 0.85;

                const hue = 270 + (i / bufferLength) * 60;
                ctx.fillStyle = `hsla(${hue}, 80%, 60%, 0.8)`;

                const y = canvas.height - barHeight;
                ctx.fillRect(x, y, barWidth - 1, barHeight);

                ctx.fillStyle = `hsla(${hue}, 80%, 60%, 0.2)`;
                ctx.fillRect(x, 0, barWidth - 1, canvas.height - barHeight);

                x += barWidth;
            }

            if (this.isRecording) {
                const elapsed = (Date.now() - this.recordingStartTime) / 1000;
                ctx.fillStyle = '#ef4444';
                ctx.beginPath();
                ctx.arc(canvas.width - 16, 16, 5, 0, 2 * Math.PI);
                ctx.fill();

                ctx.fillStyle = '#f1f5f9';
                ctx.font = '11px Inter, sans-serif';
                ctx.fillText(`${elapsed.toFixed(1)}s`, canvas.width - 50, 20);

                if (this.timerEl) {
                    this.timerEl.textContent = `${elapsed.toFixed(1)}s`;
                }
            }
        };

        draw();
    },

    startRecording() {
        if (!this.stream) {
            showToast('Microphone not initialized', 'error');
            return;
        }

        this.chunks = [];
        this.mediaRecorder = new MediaRecorder(this.stream, {
            mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                ? 'audio/webm;codecs=opus'
                : 'audio/webm',
        });

        this.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) this.chunks.push(e.data);
        };

        this.mediaRecorder.start(100);
        this.isRecording = true;
        this.recordingStartTime = Date.now();
        showToast('Recording started...', 'info');
    },

    stopRecording() {
        return new Promise((resolve) => {
            if (!this.mediaRecorder || this.mediaRecorder.state === 'inactive') {
                resolve(null);
                return;
            }

            this.mediaRecorder.onstop = async () => {
                this.isRecording = false;
                const blob = new Blob(this.chunks, { type: 'audio/webm' });

                try {
                    const wavBlob = await this.convertToWav(blob);
                    const reader = new FileReader();
                    reader.onload = () => {
                        const base64 = reader.result.split(',')[1];
                        resolve(base64);
                    };
                    reader.readAsDataURL(wavBlob);
                } catch {
                    const reader = new FileReader();
                    reader.onload = () => {
                        const base64 = reader.result.split(',')[1];
                        resolve(base64);
                    };
                    reader.readAsDataURL(blob);
                }
            };

            this.mediaRecorder.stop();
        });
    },

    async convertToWav(webmBlob) {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: 16000,
        });
        const arrayBuffer = await webmBlob.arrayBuffer();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

        const numChannels = 1;
        const sampleRate = 16000;
        const samples = audioBuffer.getChannelData(0);

        let resampled = samples;
        if (audioBuffer.sampleRate !== sampleRate) {
            const ratio = sampleRate / audioBuffer.sampleRate;
            const newLength = Math.round(samples.length * ratio);
            resampled = new Float32Array(newLength);
            for (let i = 0; i < newLength; i++) {
                const srcIdx = i / ratio;
                const idx = Math.floor(srcIdx);
                const frac = srcIdx - idx;
                resampled[i] = idx + 1 < samples.length
                    ? samples[idx] * (1 - frac) + samples[idx + 1] * frac
                    : samples[idx];
            }
        }

        const wavBuffer = this.encodeWav(resampled, sampleRate);
        audioCtx.close();
        return new Blob([wavBuffer], { type: 'audio/wav' });
    },

    encodeWav(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);

        const writeString = (offset, str) => {
            for (let i = 0; i < str.length; i++) {
                view.setUint8(offset + i, str.charCodeAt(i));
            }
        };

        writeString(0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        writeString(8, 'WAVE');
        writeString(12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        writeString(36, 'data');
        view.setUint32(40, samples.length * 2, true);

        for (let i = 0; i < samples.length; i++) {
            const s = Math.max(-1, Math.min(1, samples[i]));
            view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        }

        return buffer;
    },

    getVolume() {
        if (!this.analyser) return 0;
        const data = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteFrequencyData(data);
        return data.reduce((a, b) => a + b, 0) / data.length / 255;
    },

    stop() {
        this.isRecording = false;
        if (this.animFrameId) cancelAnimationFrame(this.animFrameId);
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        if (this.audioContext && this.audioContext.state !== 'closed') {
            this.audioContext.close();
        }
    }
};
