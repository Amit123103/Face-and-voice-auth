/**
 * FaceVoiceAuth — Settings Manager
 * Handles account security settings, activity logs, and sessions.
 */

async function loadActivityLogs() {
    const list = document.getElementById('activity-logs');
    try {
        const logs = await apiRequest('/api/account/activity');
        
        if (logs.length === 0) {
            list.innerHTML = '<p style="color: var(--text-muted); padding: 1rem;">No activity log found.</p>';
            return;
        }

        list.innerHTML = logs.map(l => `
            <div style="padding: 0.75rem 0; border-bottom: 1px solid var(--surface-border); display: flex; justify-content: space-between; align-items: start;">
                 <div>
                    <div style="font-weight: 500;">${l.action}</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted);">${formatDate(l.created_at)}</div>
                 </div>
                 <div style="text-align: right;">
                    <div style="font-size: 0.75rem; color: var(--text-muted); font-family: monospace;">${l.ip_address}</div>
                 </div>
            </div>
        `).join('');
    } catch (error) {
        list.innerHTML = `<p style="color: var(--danger); padding: 1rem;">Error loading logs: ${error.message}</p>`;
    }
}

// Initial session/security info load is handled in dashboard.html DOMContentLoaded
// but we can add refresh logic here if needed.
