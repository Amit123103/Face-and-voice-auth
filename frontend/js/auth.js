/**
 * FaceVoiceAuth — Auth Module
 * Handles login form, registration wizard, and token lifecycle.
 */

/* ── Login Handler ── */
async function handlePasswordLogin(event) {
    event.preventDefault();
    const form = event.target;
    const submitBtn = form.querySelector('button[type="submit"]');
    const email = form.querySelector('#login-email').value.trim();
    const password = form.querySelector('#login-password').value;
    const totpCode = form.querySelector('#login-totp')?.value.trim() || '';

    if (!email || !password) {
        showToast('Please fill in all fields', 'warning');
        return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner spinner-sm"></span> Signing in...';

    try {
        const data = await apiRequest('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password, totp_code: totpCode || null }),
        });

        TokenStore.set(data.access_token);

        const profile = await apiRequest('/api/auth/me');
        TokenStore.setUserData(profile);

        showToast('Login successful!', 'success');
        setTimeout(() => {
            window.location.href = profile.role === 'admin' ? '/admin.html' : '/dashboard.html';
        }, 500);
    } catch (error) {
        showToast(error.message, 'error');
        if (error.message.includes('2FA')) {
            showElement('#totp-group');
        }
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '🔐 Sign In';
    }
}

/* ── Registration Handler ── */
const RegistrationWizard = {
    currentStep: 1,
    totalSteps: 7,
    userData: {},

    init() {
        this.showStep(1);
        this.bindNavigation();
    },

    showStep(step) {
        for (let i = 1; i <= this.totalSteps; i++) {
            const el = $(`#reg-step-${i}`);
            if (el) {
                el.classList.toggle('active', i === step);
                el.classList.toggle('hidden', i !== step);
            }
        }
        this.currentStep = step;
        this.updateProgressBar();
    },

    updateProgressBar() {
        const bar = $('#reg-progress-bar');
        if (bar) {
            const percent = Math.round((this.currentStep / this.totalSteps) * 100);
            bar.style.width = `${percent}%`;
        }
        const label = $('#reg-step-label');
        if (label) {
            const labels = [
                '', 'Account Info', 'Password', 'Auth Modes',
                'Face Enrollment', 'Voice Enrollment', '2FA Setup', 'Complete'
            ];
            label.textContent = `Step ${this.currentStep}: ${labels[this.currentStep]}`;
        }
    },

    bindNavigation() {
        $$('.reg-next-btn').forEach(btn => {
            btn.addEventListener('click', () => this.nextStep());
        });
        $$('.reg-prev-btn').forEach(btn => {
            btn.addEventListener('click', () => this.prevStep());
        });
    },

    async nextStep() {
        if (!this.validateCurrentStep()) return;

        if (this.currentStep === 1) {
            this.userData.email = $('#reg-email')?.value.trim();
            this.userData.username = $('#reg-username')?.value.trim();
            this.userData.full_name = $('#reg-fullname')?.value.trim();
        } else if (this.currentStep === 2) {
            this.userData.password = $('#reg-password')?.value;
        } else if (this.currentStep === 3) {
            const radios = $$('input[name="auth-mode"]');
            radios.forEach(r => { if (r.checked) this.userData.auth_mode = r.value; });
        }

        if (this.currentStep === 2) {
            try {
                await this.submitRegistration();
            } catch (error) {
                showToast(error.message, 'error');
                return;
            }
        }

        if (this.currentStep === 3) {
            const mode = this.userData.auth_mode || 'password';
            if (mode === 'password') {
                this.showStep(6);
                return;
            } else if (mode === 'face') {
                this.showStep(4);
                return;
            } else if (mode === 'voice') {
                this.showStep(5);
                return;
            }
        }

        if (this.currentStep < this.totalSteps) {
            this.showStep(this.currentStep + 1);
        }
    },

    prevStep() {
        if (this.currentStep > 1) {
            this.showStep(this.currentStep - 1);
        }
    },

    validateCurrentStep() {
        if (this.currentStep === 1) {
            const email = $('#reg-email')?.value.trim();
            const username = $('#reg-username')?.value.trim();
            const fullName = $('#reg-fullname')?.value.trim();
            if (!email || !username || !fullName) {
                showToast('Please fill in all fields', 'warning');
                return false;
            }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                showToast('Please enter a valid email', 'warning');
                return false;
            }
            return true;
        }
        if (this.currentStep === 2) {
            const password = $('#reg-password')?.value;
            const confirm = $('#reg-password-confirm')?.value;
            if (!password || password.length < 8) {
                showToast('Password must be at least 8 characters', 'warning');
                return false;
            }
            if (password !== confirm) {
                showToast('Passwords do not match', 'warning');
                return false;
            }
            return true;
        }
        return true;
    },

    async submitRegistration() {
        const data = await apiRequest('/api/auth/register', {
            method: 'POST',
            body: JSON.stringify(this.userData),
        });

        const loginData = await apiRequest('/api/auth/login', {
            method: 'POST',
            body: JSON.stringify({
                email: this.userData.email,
                password: this.userData.password,
            }),
        });

        TokenStore.set(loginData.access_token);
        TokenStore.setUserData(data);
        showToast('Account created!', 'success');
    },

    complete() {
        showToast('Registration complete! Redirecting...', 'success');
        setTimeout(() => {
            window.location.href = '/dashboard.html';
        }, 1000);
    }
};

/* ── Logout ── */
async function handleLogout() {
    try {
        await apiRequest('/api/auth/logout', { method: 'POST' });
    } catch {}
    TokenStore.clear();
    showToast('Logged out', 'info');
    setTimeout(() => { window.location.href = '/login.html'; }, 500);
}
