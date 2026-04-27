/**
 * FaceVoiceAuth — Camera Module
 * WebRTC camera access, real-time face detection overlay, quality checks.
 */

const CameraModule = {
    stream: null,
    videoEl: null,
    canvasEl: null,
    ctx: null,
    isActive: false,
    animFrameId: null,

    async init(videoSelector, canvasSelector) {
        this.videoEl = typeof videoSelector === 'string' ? $(videoSelector) : videoSelector;
        this.canvasEl = typeof canvasSelector === 'string' ? $(canvasSelector) : canvasSelector;

        if (!this.videoEl || !this.canvasEl) {
            showToast('Camera elements not found', 'error');
            return false;
        }

        this.ctx = this.canvasEl.getContext('2d');

        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    facingMode: 'user',
                },
                audio: false,
            });

            this.videoEl.srcObject = this.stream;
            await this.videoEl.play();

            this.canvasEl.width = this.videoEl.videoWidth || 640;
            this.canvasEl.height = this.videoEl.videoHeight || 480;

            this.isActive = true;
            this.drawLoop();

            showToast('Camera activated', 'success');
            return true;
        } catch (error) {
            let msg = 'Camera access denied';
            if (error.name === 'NotFoundError') msg = 'No camera detected';
            else if (error.name === 'NotAllowedError') msg = 'Camera permission denied';
            else if (error.name === 'NotReadableError') msg = 'Camera is in use by another app';
            showToast(msg, 'error');
            return false;
        }
    },

    drawLoop() {
        if (!this.isActive) return;

        this.ctx.drawImage(this.videoEl, 0, 0, this.canvasEl.width, this.canvasEl.height);

        this.drawFaceGuide();

        this.animFrameId = requestAnimationFrame(() => this.drawLoop());
    },

    drawFaceGuide() {
        const w = this.canvasEl.width;
        const h = this.canvasEl.height;
        const cx = w / 2;
        const cy = h / 2;
        const rx = w * 0.22;
        const ry = h * 0.32;

        this.ctx.beginPath();
        this.ctx.ellipse(cx, cy, rx, ry, 0, 0, 2 * Math.PI);
        this.ctx.strokeStyle = 'rgba(99, 102, 241, 0.5)';
        this.ctx.lineWidth = 2;
        this.ctx.setLineDash([8, 6]);
        this.ctx.stroke();
        this.ctx.setLineDash([]);

        const corners = [
            [cx - rx, cy - ry], [cx + rx, cy - ry],
            [cx - rx, cy + ry], [cx + rx, cy + ry],
        ];
        const cornerLen = 20;
        this.ctx.strokeStyle = 'rgba(99, 102, 241, 0.8)';
        this.ctx.lineWidth = 3;
        this.ctx.setLineDash([]);

        corners.forEach(([x, y]) => {
            const dx = x < cx ? 1 : -1;
            const dy = y < cy ? 1 : -1;
            this.ctx.beginPath();
            this.ctx.moveTo(x + dx * cornerLen, y);
            this.ctx.lineTo(x, y);
            this.ctx.lineTo(x, y + dy * cornerLen);
            this.ctx.stroke();
        });
    },

    drawBoundingBox(x, y, w, h, color = '#22c55e') {
        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 2;
        this.ctx.strokeRect(x, y, w, h);
    },

    captureFrame() {
        if (!this.isActive || !this.videoEl) return null;

        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = this.videoEl.videoWidth || 640;
        tempCanvas.height = this.videoEl.videoHeight || 480;
        const tempCtx = tempCanvas.getContext('2d');
        tempCtx.drawImage(this.videoEl, 0, 0);

        return tempCanvas.toDataURL('image/jpeg', 0.85).split(',')[1];
    },

    captureMultipleFrames(count = 3, intervalMs = 500) {
        return new Promise((resolve) => {
            const frames = [];
            let captured = 0;

            const capture = () => {
                const frame = this.captureFrame();
                if (frame) {
                    frames.push(frame);
                    captured++;
                }
                if (captured >= count) {
                    resolve(frames);
                } else {
                    setTimeout(capture, intervalMs);
                }
            };

            capture();
        });
    },

    checkQuality() {
        if (!this.isActive) return { ok: false, issues: ['Camera not active'] };

        const issues = [];
        const w = this.videoEl.videoWidth || 0;
        const h = this.videoEl.videoHeight || 0;

        if (w < 480 || h < 360) issues.push('Resolution too low (min 480p)');

        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = w;
        tempCanvas.height = h;
        const ctx = tempCanvas.getContext('2d');
        ctx.drawImage(this.videoEl, 0, 0);
        const imageData = ctx.getImageData(0, 0, w, h);
        const data = imageData.data;

        let totalBrightness = 0;
        for (let i = 0; i < data.length; i += 16) {
            totalBrightness += (data[i] + data[i + 1] + data[i + 2]) / 3;
        }
        const avgBrightness = totalBrightness / (data.length / 16);
        if (avgBrightness < 40) issues.push('Too dark — increase lighting');
        if (avgBrightness > 230) issues.push('Too bright — reduce lighting');

        return { ok: issues.length === 0, issues, brightness: Math.round(avgBrightness) };
    },

    stop() {
        this.isActive = false;
        if (this.animFrameId) cancelAnimationFrame(this.animFrameId);
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        if (this.videoEl) this.videoEl.srcObject = null;
    },

    showLivenessPrompt(text) {
        let prompt = this.canvasEl?.parentElement?.querySelector('.liveness-prompt');
        if (!prompt) {
            prompt = document.createElement('div');
            prompt.className = 'liveness-prompt';
            this.canvasEl?.parentElement?.appendChild(prompt);
        }
        prompt.textContent = text;
        prompt.style.display = 'block';
    },

    hideLivenessPrompt() {
        const prompt = this.canvasEl?.parentElement?.querySelector('.liveness-prompt');
        if (prompt) prompt.style.display = 'none';
    }
};
