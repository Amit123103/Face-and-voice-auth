// Documents Features Logic

// ==========================================
// DOCUMENTS
// ==========================================

async function loadDocuments() {
    try {
        const docs = await apiRequest('/api/documents/');
        const container = document.getElementById('documents-list');
        
        if (docs.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted); padding: 1rem;">No documents uploaded yet.</p>';
            return;
        }

        container.innerHTML = docs.map(d => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem 0; border-bottom: 1px solid var(--surface-border);">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <div style="font-size: 2rem;">📄</div>
                    <div>
                        <div style="font-weight: 500;">${escapeHtml(d.filename)}</div>
                        <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 5px;">
                            ${(d.file_size / 1024).toFixed(1)} KB • Uploaded ${new Date(d.created_at).toLocaleDateString()}
                        </div>
                    </div>
                </div>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-primary btn-sm" onclick="downloadDocument('${d.id}', '${escapeHtml(d.filename)}')">⬇ Download</button>
                    <button class="btn btn-ghost btn-sm" onclick="deleteDocument('${d.id}')">🗑</button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        document.getElementById('documents-list').innerHTML = `<p style="color: var(--danger); padding: 1rem;">Error loading documents.</p>`;
    }
}

async function handleDocumentUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (file.size > 10 * 1024 * 1024) {
        showToast("File is too large! Maximum 10MB.", "error");
        event.target.value = '';
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const token = TokenStore.getAccessToken();
        const res = await fetch('/api/documents/upload', {
            method: 'POST',
            body: formData,
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || 'Upload failed');
        }
        
        showToast("Document uploaded successfully", "success");
        event.target.value = '';
        await loadDocuments();
    } catch (error) {
        showToast(error.message, "error");
    }
}

async function downloadDocument(docId, filename) {
    try {
        const token = TokenStore.getAccessToken();
        const res = await fetch(`/api/documents/${docId}/download`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!res.ok) throw new Error('Download failed');
        
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function deleteDocument(docId) {
    if (!confirm('Are you sure you want to delete this document?')) return;
    try {
        await apiRequest(`/api/documents/${docId}`, { method: 'DELETE' });
        showToast("Document deleted", "success");
        await loadDocuments();
    } catch (error) {
        showToast(error.message, 'error');
    }
}
