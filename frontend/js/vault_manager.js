/**
 * FaceVoiceAuth — Vault Manager
 * Handles dynamic secret types, category filtering, and encryption payload structure.
 */

let currentVaultCategory = 'All';
let currentVaultType = null;

function updateVaultFields() {
    const type = document.getElementById('vault-type').value;
    const container = document.getElementById('vault-dynamic-fields');
    
    let html = '';
    
    if (type === 'Note') {
        html = `
            <div class="form-group">
                <label>Secret Content</label>
                <textarea id="vault-note-content" class="form-control" style="min-height: 120px;" placeholder="Lat: 34.05, Long: -118.24..."></textarea>
            </div>
        `;
    } else if (type === 'Financial') {
        html = `
            <div class="form-group"><label>Platform / Bank Name</label><input type="text" id="v-fin-bank" class="form-control" placeholder="Chase / Binance / MetaMask"></div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                <div class="form-group"><label>Account / Wallet Address</label><input type="text" id="v-fin-acc" class="form-control" placeholder="XXXX-XXXX-XXXX"></div>
                <div class="form-group"><label>UPI ID (if any)</label><input type="text" id="v-fin-upi" class="form-control" placeholder="user@upi"></div>
            </div>
            <div class="form-group"><label>Crypto Network / Card Type</label><input type="text" id="v-fin-network" class="form-control" placeholder="Ethereum / Visa (Last 4 digits)"></div>
        `;
    } else if (type === 'Password') {
        html = `
            <div class="form-group"><label>App / Website Name</label><input type="text" id="v-pass-url" class="form-control" placeholder="Google / Twitter"></div>
            <div class="form-group"><label>Username / Email</label><input type="text" id="v-pass-user" class="form-control" placeholder="user@mail.com"></div>
            <div class="form-group"><label>Password</label>
                <div style="position: relative;">
                    <input type="password" id="v-pass-val" class="form-control" placeholder="••••••••">
                    <button class="btn btn-ghost btn-sm" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%);" onclick="togglePassVisibility('v-pass-val')">👁</button>
                </div>
            </div>
        `;
    } else if (type === 'ID') {
        html = `
            <div class="form-group"><label>Document Type</label>
                <select id="v-id-type-list" class="form-control">
                    <option value="Aadhaar">🇮🇳 Aadhaar Card</option>
                    <option value="PAN">🆔 PAN Card</option>
                    <option value="Passport">🛂 Passport</option>
                    <option value="Driving License">🚗 Driving License</option>
                    <option value="Custom">📎 Other ID</option>
                </select>
            </div>
            <div class="form-group"><label>ID / Passport Number</label><input type="text" id="v-id-num" class="form-control" placeholder="0000 0000 0000"></div>
            <div class="form-group"><label>Expiry Date (Optional)</label><input type="date" id="v-id-expiry" class="form-control"></div>
        `;
    }
    
    container.innerHTML = html;
}

function togglePassVisibility(id) {
    const el = document.getElementById(id);
    el.type = el.type === 'password' ? 'text' : 'password';
}

async function saveVaultNote() {
    const title = document.getElementById('vault-note-title').value;
    const category = document.getElementById('vault-category').value;
    const type = document.getElementById('vault-type').value;
    const id = document.getElementById('vault-note-id').value;
    
    if (!title) return showToast('Title is required', 'warning');
    
    let content = '';
    
    // Structure content based on type
    if (type === 'Note') {
        content = document.getElementById('vault-note-content').value;
    } else if (type === 'Financial') {
        content = JSON.stringify({
            'Bank/Platform': document.getElementById('v-fin-bank').value,
            'Account/Wallet': document.getElementById('v-fin-acc').value,
            'UPI ID': document.getElementById('v-fin-upi').value,
            'Network/Suffix': document.getElementById('v-fin-network').value
        });
    } else if (type === 'Password') {
        content = JSON.stringify({
            'Service': document.getElementById('v-pass-url').value,
            'Username': document.getElementById('v-pass-user').value,
            'Password': document.getElementById('v-pass-val').value
        });
    } else if (type === 'ID') {
        content = JSON.stringify({
            'ID Type': document.getElementById('v-id-type-list').value,
            'Number': document.getElementById('v-id-num').value,
            'Expiry': document.getElementById('v-id-expiry').value || 'None'
        });
    }

    try {
        const method = id ? 'PUT' : 'POST';
        const url = id ? `/api/vault/${id}` : '/api/vault';
        
        await apiRequest(url, {
            method,
            body: JSON.stringify({ title, content, category, secret_type: type })
        });
        
        showToast('Secret encrypted & saved!', 'success');
        document.getElementById('vault-modal').style.display = 'none';
        loadVaultNotes();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function filterVault(category) {
    currentVaultCategory = category;
    document.querySelectorAll('#tab-vault .btn-ghost').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    loadVaultNotes();
}

function filterVaultType(type) {
    currentVaultType = currentVaultType === type ? null : type;
    loadVaultNotes();
}

async function loadVaultNotes() {
    const list = document.getElementById('vault-list');
    try {
        let secrets = await apiRequest('/api/vault');
        
        // Frontend filtering
        if (currentVaultCategory !== 'All') {
            secrets = secrets.filter(s => s.category === currentVaultCategory);
        }
        if (currentVaultType) {
            secrets = secrets.filter(s => s.secret_type === currentVaultType);
        }

        if (secrets.length === 0) {
            list.innerHTML = '<p style="color: var(--text-muted); padding: 1rem; grid-column: 1/-1;">No secrets found in this category.</p>';
            return;
        }

        list.innerHTML = secrets.map(s => {
            const iconMap = { 'Financial': '💰', 'Password': '🔑', 'ID': '📎', 'Note': '📝' };
            const icon = iconMap[s.secret_type] || '🔒';
            return `
                <div class="card" style="padding: 1rem; position: relative; border-left: 3px solid var(--accent-indigo);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                        <span style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">
                            ${icon} ${s.category}
                        </span>
                        <span class="badge" style="font-size: 0.6rem; opacity: 0.8;">🔒 ONLY ME</span>
                    </div>
                    <h4 style="margin-bottom: 1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${s.title}</h4>
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn btn-primary btn-sm" style="flex:1" onclick="viewSecret('${s.id}')">👁 View</button>
                        <button class="btn btn-ghost btn-sm" onclick="deleteSecret('${s.id}')" title="Delete">🗑</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        list.innerHTML = `<p style="color: var(--danger); padding: 1rem;">Error loading vault: ${error.message}</p>`;
    }
}

async function viewSecret(id) {
    try {
        const secret = await apiRequest(`/api/vault/${id}`);
        let rows = '';
        
        // Try parsing JSON for structured items
        try {
            const data = JSON.parse(secret.content);
            rows = Object.entries(data).map(([k, v]) => `
                <div style="margin-bottom: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.4rem;">
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.2rem;">${k}</div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="font-family: monospace; color: var(--text-primary);">${v}</div>
                        <button class="btn btn-ghost btn-sm" style="padding: 2px 6px;" onclick="copyToClipboard('${v}')" title="Copy">📋</button>
                    </div>
                </div>
            `).join('');
        } catch(e) { 
            rows = `
                <div style="font-family: monospace; white-space: pre-wrap; color: var(--text-primary); background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 8px;">${secret.content}</div>
                <button class="btn btn-ghost btn-sm" style="margin-top:0.5rem; width: 100%;" onclick="copyToClipboard('${secret.content.replace(/'/g, "\\'")}')">📋 Copy Content</button>
            `;
        }

        const modalHtml = `
            <div style="padding: 1.5rem;">
                <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1.5rem;">
                    <div style="font-size: 1.5rem;">🛡️</div>
                    <div>
                        <h3 style="margin-bottom: 0.1rem;">${secret.title}</h3>
                        <div style="font-size: 0.75rem; color: var(--text-muted);">${secret.category} — Vault Item</div>
                    </div>
                </div>
                <div style="margin-bottom: 2rem;">${rows}</div>
                <button class="btn btn-primary w-100" onclick="closeModal()">✕ Done</button>
            </div>
        `;
        
        const viewModal = document.createElement('div');
        viewModal.id = 'temp-view-modal';
        viewModal.className = 'modal';
        viewModal.style.display = 'flex';
        viewModal.style.position = 'fixed';
        viewModal.style.top = '0';
        viewModal.style.left = '0';
        viewModal.style.width = '100%';
        viewModal.style.height = '100%';
        viewModal.style.background = 'rgba(0,0,0,0.85)';
        viewModal.style.zIndex = '2000';
        viewModal.style.alignItems = 'center';
        viewModal.style.justifyContent = 'center';
        viewModal.style.backdropFilter = 'blur(10px)';
        
        viewModal.innerHTML = `<div class="card" style="width: 450px; border: 1px solid var(--accent-indigo); box-shadow: 0 0 30px rgba(99, 102, 241, 0.2);">${modalHtml}</div>`;
        document.body.appendChild(viewModal);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard!', 'success');
    }).catch(err => {
        showToast('Failed to copy', 'error');
    });
}

function closeModal() {
    const m = document.getElementById('temp-view-modal');
    if (m) m.remove();
}

async function deleteSecret(id) {
    if (!confirm('Are you sure you want to delete this secret?')) return;
    try {
        await apiRequest(`/api/vault/${id}`, { method: 'DELETE' });
        showToast('Secret deleted permanently', 'info');
        loadVaultNotes();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function openVaultModal() {
    document.getElementById('vault-modal').style.display = 'flex';
    document.getElementById('vault-note-id').value = '';
    document.getElementById('vault-note-title').value = '';
    updateVaultFields();
}
