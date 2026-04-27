const AdminPanel = {
    currentSection: 'overview',

    async init() {
        if (!requireAuth() || !requireAdmin()) return;
        
        // Initialize Theme System
        if (window.ThemeManager) {
            ThemeManager.init();
            const toggle = $('#theme-toggle');
            if (toggle) toggle.addEventListener('click', () => ThemeManager.toggle());
        }

        this.bindSidebar();
        this.showSection('overview');
        this.loadOverviewStats();
    },

    bindSidebar() {
        $$('.sidebar-item').forEach(item => {
            item.addEventListener('click', () => {
                $$('.sidebar-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                this.showSection(item.dataset.section);
            });
        });
    },

    showSection(section) {
        this.currentSection = section;
        $$('.admin-section').forEach(s => s.classList.add('hidden'));
        $(`#admin-${section}`)?.classList.remove('hidden');

        const loaders = {
            overview: () => this.loadOverviewStats(),
            users: () => this.loadUsers(),
            ledger: () => this.loadLedger(),
            audit: () => this.loadAuditLog(),
            health: () => this.loadSystemHealth(),
            backups: () => this.loadBackups(),
        };
        if (loaders[section]) loaders[section]();
    },

    async loadOverviewStats() {
        try {
            const health = await apiRequest('/api/admin/health');
            const users = await apiRequest('/api/admin/users?limit=1'); // to get total count
            
            $('#stat-total-users').textContent = users.total_count;
            $('#stat-active-sessions').textContent = health.stats.active_sessions;
            $('#stat-failed-logins').textContent = health.stats.failed_logins_24h;
            
            // Calculate a mock platform security average (or fetch real if available)
            $('#stat-security-avg').textContent = '82%'; 
        } catch (error) {
            console.error('Failed to load overview stats', error);
        }
    },

    async loadUsers() {
        const container = $('#users-table-body');
        if (!container) return;

        try {
            const data = await apiRequest('/api/admin/users?limit=50');

            container.innerHTML = data.users.map(user => {
                const scoreColor = user.security_score >= 80 ? 'var(--teal)' : (user.security_score >= 50 ? 'var(--warning)' : 'var(--danger)');
                
                return `
                <tr>
                    <td>
                        <div style="display: flex; align-items: center; gap: 0.75rem;">
                            <div class="user-avatar" style="background: var(--surface-hover);">${user.full_name.charAt(0)}</div>
                            <div>
                                <div style="font-weight: 600;">${escapeHtml(user.full_name)}</div>
                                <div style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(user.email)}</div>
                            </div>
                        </div>
                    </td>
                    <td><span class="badge ${user.role === 'admin' ? 'badge-primary' : ''}">${user.role}</span></td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <div style="width: 40px; height: 6px; background: var(--surface-hover); border-radius: 3px; overflow: hidden;">
                                <div style="width: ${user.security_score}%; height: 100%; background: ${scoreColor};"></div>
                            </div>
                            <span style="font-weight: 600; font-size: 0.85rem; color: ${scoreColor}">${user.security_score}%</span>
                        </div>
                    </td>
                    <td>
                        ${user.face_enrolled ? '📸' : ''} ${user.voice_enrolled ? '🎙️' : ''} ${user.totp_enabled ? '🔐' : ''}
                        ${!user.face_enrolled && !user.voice_enrolled ? '<span class="text-danger">None</span>' : ''}
                    </td>
                    <td>${user.is_active ? '<span class="status-dot online"></span> Active' : '<span class="status-dot offline"></span> Locked'}</td>
                    <td>
                        <div class="btn-group">
                            <button class="btn btn-ghost btn-xs" onclick="AdminPanel.revokeUserSessions('${user.id}')" title="Revoke Access">🚫</button>
                            <button class="btn btn-ghost btn-xs" onclick="AdminPanel.deleteUser('${user.id}')" title="Suspend">🗑️</button>
                        </div>
                    </td>
                </tr>
            `}).join('');

            $('#users-count').textContent = data.total_count;
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async revokeUserSessions(userId) {
        if (!confirm('Kick all active sessions for this user?')) return;
        try {
            const result = await apiRequest(`/api/admin/users/${userId}/revoke-sessions`, { method: 'POST' });
            showToast(result.message, 'success');
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async deleteUser(userId) {
        if (!confirm('Are you sure you want to suspend this user?')) return;
        try {
            const result = await apiRequest(`/api/admin/users/${userId}`, { method: 'DELETE' });
            showToast(result.message, 'success');
            this.loadUsers();
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async loadLedger() {
        try {
            const txns = await apiRequest('/api/admin/transactions');
            const container = $('#ledger-table-body');
            if (!container) return;
            
            if (txns.length === 0) {
                container.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No network transactions detected.</td></tr>';
                return;
            }
            
            container.innerHTML = txns.map(t => {
                const statusClass = t.status === 'completed' ? 'text-success' : (t.status === 'failed' ? 'text-danger' : 'text-warning');
                
                return `
                    <tr>
                        <td>${formatDate(t.created_at)}</td>
                        <td>${escapeHtml(t.sender_email)}</td>
                        <td>${escapeHtml(t.receiver_email)}</td>
                        <td class="text-primary" style="font-weight: 700;">$${t.amount.toFixed(2)}</td>
                        <td class="${statusClass}">${t.status.toUpperCase()}</td>
                        <td>
                            ${t.status === 'receiver_verified' 
                                ? `<button class="btn btn-primary btn-xs" onclick="AdminPanel.approveTransaction('${t.id}')">Approve Release</button>` 
                                : '-'}
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async approveTransaction(txnId) {
        try {
            await apiRequest(`/api/admin/transactions/${txnId}/approve`, { method: 'PATCH' });
            showToast('Funds Released!', 'success');
            this.loadLedger();
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async loadAuditLog() {
        // Master view shows all recent logs if no user specified
        const userIdInput = $('#audit-user-id')?.value.trim();
        const url = userIdInput ? `/api/admin/users/${userIdInput}/audit` : '/api/admin/health'; // health returns some stats, but we want a real master audit
        
        // For master audit, we'll try to fetch recent logs from the DB if available,
        // but for now we'll stick to searching by User ID as requested in previous requirements.
        if (!userIdInput) {
            const container = $('#audit-log-body');
            container.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Enter a search term to scan master archives.</td></tr>';
            return;
        }
        this.searchAuditLog();
    },

    async searchAuditLog() {
        const term = $('#audit-user-id')?.value.trim();
        try {
            const data = await apiRequest(`/api/admin/users/${term}/audit`);
            const container = $('#audit-log-body');
            
            container.innerHTML = data.entries.map(entry => `
                <tr>
                    <td>${formatDate(entry.created_at)}</td>
                    <td>${escapeHtml(entry.user_id || 'system')}</td>
                    <td><span class="badge">${entry.action}</span></td>
                    <td>${entry.status_code}</td>
                    <td>${entry.ip_address}</td>
                </tr>
            `).join('');
        } catch (error) {
            showToast('Audit scan failed: ' + error.message, 'error');
        }
    },

    async loadSystemHealth() {
        try {
            const data = await apiRequest('/api/admin/health');
            const container = $('#health-content');
            
            container.innerHTML = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                    <div class="glass-card">
                        <h5>Database</h5>
                        <div class="${data.database === 'healthy' ? 'text-success' : 'text-danger'}">${data.database.toUpperCase()}</div>
                    </div>
                    <div class="glass-card">
                        <h5>Face Model</h5>
                        <div class="${data.face_model_loaded ? 'text-success' : 'text-warning'}">${data.face_model_loaded ? 'ONLINE' : 'OFFLINE'}</div>
                    </div>
                    <div class="glass-card">
                        <h5>Voice Model</h5>
                        <div class="${data.voice_model_loaded ? 'text-success' : 'text-warning'}">${data.voice_model_loaded ? 'ONLINE' : 'OFFLINE'}</div>
                    </div>
                </div>
            `;
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async loadBackups() {
        try {
            const data = await apiRequest('/api/admin/backups');
            const container = $('#backups-list');
            
            container.innerHTML = data.backups.length 
                ? data.backups.map(b => `
                    <div style="display: flex; justify-content: space-between; padding: 0.5rem; border-bottom: 1px solid var(--surface-hover);">
                        <span>${b.filename}</span>
                        <span class="text-muted">${(b.size_bytes/1024).toFixed(1)}KB</span>
                    </div>
                `).join('')
                : 'No snapshots available.';
        } catch (error) {
            showToast(error.message, 'error');
        }
    },

    async triggerBackup() {
        try {
            const result = await apiRequest('/api/admin/backup', { method: 'POST' });
            showToast('Platform Snapshot Created!', 'success');
            this.loadBackups();
        } catch (error) {
            showToast(error.message, 'error');
        }
    }
};
