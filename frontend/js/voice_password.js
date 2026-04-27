/**
 * FaceVoiceAuth — Voice Password Module
 * Handles custom passphrase enrollment and management.
 */

let voicePassRecorder = null;
let voicePassAudioBase64 = null;

async function openVoicePasswordModal() {
    const modal = document.getElementById('voice-pass-modal');
    modal.style.display = 'flex';
    
    // Check current status
    const user = TokenStore.getUserData();
    const statusEl = document.getElementById('vpass-status');
    const disableBtn = document.getElementById('vpass-disable-btn');
    
    if (user && user.voice_passphrase_enabled) {
        statusEl.innerHTML = '✅ Voice Password is <span style="color:var(--success)">ENABLED</span>';
        disableBtn.style.display = 'block';
    } else {
        statusEl.innerHTML = '⚠️ Voice Password is <span style="color:var(--warning)">DISABLED</span>';
        disableBtn.style.display = 'none';
    }

    // Reset recording state
    document.getElementById('vpass-preview').style.display = 'none';
    document.getElementById('vpass-record-btn').innerHTML = '🔴 Start Recording';
    document.getElementById('vpass-record-btn').className = 'btn btn-purple';
}

function closeVoicePassModal() {
    document.getElementById('voice-pass-modal').style.display = 'none';
    MicrophoneModule.stop();
}

async function toggleVoicePassRecording() {
    const btn = document.getElementById('vpass-record-btn');
    const statusEl = document.getElementById('vpass-status');
    
    if (!MicrophoneModule.isRecording) {
        const ok = await MicrophoneModule.init();
        if (!ok) return;
        
        MicrophoneModule.startRecording();
        btn.innerHTML = '⏹ Stop Recording';
        btn.className = 'btn btn-danger';
        statusEl.textContent = 'Recording your secret phrase...';
    } else {
        btn.innerHTML = '<span class="spinner spinner-sm"></span> Processing...';
        btn.disabled = true;
        
        voicePassAudioBase64 = await MicrophoneModule.stopRecording();
        btn.disabled = false;
        btn.innerHTML = '🔴 Start Recording';
        btn.className = 'btn btn-purple';
        
        if (voicePassAudioBase64) {
            processVoicePassphrase();
        }
    }
}

async function processVoicePassphrase() {
    const statusEl = document.getElementById('vpass-status');
    statusEl.innerHTML = '<span class="spinner spinner-sm"></span> AI Processing & Transcribing...';
    
    try {
        const result = await apiRequest('/api/voice/passphrase/set', {
            method: 'POST',
            body: JSON.stringify({ audio_base64: voicePassAudioBase64 })
        });
        
        const preview = document.getElementById('vpass-preview');
        const textEl = document.getElementById('vpass-text');
        
        preview.style.display = 'block';
        textEl.innerHTML = `
            <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 8px; border: 1px solid var(--accent-indigo); margin-bottom: 1rem;">
                <span style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 0.5rem;">YOUR SECRET PHRASE</span>
                <span style="font-size: 1.2rem; font-weight: bold; color: var(--accent-indigo); letter-spacing: 0.05em;">"${result.passphrase}"</span>
            </div>
        `;
        statusEl.innerHTML = '✅ <span style="color:var(--success)">HEARD LOUD & CLEAR</span>';
        showToast('Transcription successful. Verify and confirm.', 'success');
        
    } catch (error) {
        statusEl.innerHTML = '❌ <span style="color:var(--danger)">NOT RECOGNIZED</span>';
        showToast(error.message, 'error');
    }
}

async function saveVoicePassphrase() {
    showToast('Voice password activated!', 'success');
    
    // Refresh user data to update the UI badges
    const user = await apiRequest('/api/auth/me');
    TokenStore.setUserData(user);
    
    // Update dashboard badges immediately if they exist
    const statusBadges = document.querySelectorAll('#dash-voice-status, #settings-voice-badge');
    statusBadges.forEach(b => b.innerHTML = '<span class="badge badge-success">Enrolled</span>');

    closeVoicePassModal();
    if (typeof loadTransactions === 'function') loadTransactions();
}

async function disableVoicePassphrase() {
    if (!confirm('Are you sure you want to disable your voice password? This will reduce your security score.')) return;
    
    try {
        await apiRequest('/api/voice/passphrase/disable', { method: 'POST' });
        showToast('Voice password disabled', 'info');
        
        const user = await apiRequest('/api/auth/me');
        TokenStore.setUserData(user);
        
        closeVoicePassModal();
    } catch (error) {
        showToast(error.message, 'error');
    }
}
