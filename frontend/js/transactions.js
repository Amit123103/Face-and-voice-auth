let currentTxnId = null;
let currentTxnAction = null; // 'sender' or 'receiver'
let txnVideoStream = null;

async function loadTransactions() {
    try {
        const txns = await apiRequest('/api/transactions/');
        const container = document.getElementById('transactions-list');
        const userEmail = TokenStore.getUserData()?.email;
        
        if (txns.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted); padding: 1rem;">No transactions found.</p>';
            return;
        }

        container.innerHTML = txns.map(t => {
            const isSender = t.sender_email === userEmail;
            const directionIcon = isSender ? '💸' : '📥';
            const counterparty = isSender ? `To: ${t.receiver_email}` : `From: ${t.sender_email}`;
            const amountColor = isSender ? 'var(--danger)' : 'var(--teal)';
            
            let statusBadge = '';
            let actionHtml = '';

            // Status Logic
            if (t.status === 'pending') {
                statusBadge = '<span class="badge badge-warning">Pending</span>';
                if (isSender && !t.sender_face_verified) {
                    actionHtml = `<button class="btn btn-teal btn-sm" onclick="openVerifyModal('${t.id}', 'sender')">Verify Send 📸</button>`;
                } else if (!isSender && !t.receiver_face_verified) {
                    // Receiver can't verify until sender does (or they can, but let's prompt anyway)
                    actionHtml = `<button class="btn btn-teal btn-sm" onclick="openVerifyModal('${t.id}', 'receiver')">Claim Funds 📸</button>`;
                } else {
                    statusBadge = '<span class="badge badge-warning">Waiting for other party</span>';
                }
            } else if (t.status === 'sender_verified' || t.status === 'receiver_verified') {
                statusBadge = '<span class="badge badge-warning">Partial Verification</span>';
                if (isSender && !t.sender_face_verified) {
                    actionHtml = `<button class="btn btn-teal btn-sm" onclick="openVerifyModal('${t.id}', 'sender')">Verify Send 📸</button>`;
                } else if (!isSender && !t.receiver_face_verified) {
                    actionHtml = `<button class="btn btn-teal btn-sm" onclick="openVerifyModal('${t.id}', 'receiver')">Claim Funds 📸</button>`;
                } else {
                    statusBadge = '<span class="badge badge-warning">Awaiting Admin Approval</span>';
                }
            } else if (t.status === 'completed') {
                statusBadge = '<span class="badge badge-success">Completed</span>';
            } else if (t.status === 'failed') {
                statusBadge = '<span class="badge badge-danger">Failed</span>';
            }

            return `
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem 0; border-bottom: 1px solid var(--surface-border);">
                    <div>
                        <div style="font-weight: 500; display: flex; align-items: center; gap: 0.5rem;">
                            ${directionIcon} ${counterparty} ${statusBadge}
                        </div>
                        <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 5px;">Created: ${new Date(t.created_at).toLocaleString()}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 1.2rem; font-weight: bold; color: ${amountColor};">$${t.amount.toFixed(2)}</div>
                        <div style="margin-top: 5px;">${actionHtml}</div>
                    </div>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Failed to load transactions:', error);
        document.getElementById('transactions-list').innerHTML = `<p style="color: var(--danger); padding: 1rem;">Error loading transactions</p>`;
    }
}

function openSendMoneyModal() {
    document.getElementById('transfer-email').value = '';
    document.getElementById('transfer-amount').value = '';
    document.getElementById('transfer-modal').style.display = 'flex';
}

async function submitTransfer() {
    const email = document.getElementById('transfer-email').value;
    const amount = parseFloat(document.getElementById('transfer-amount').value);
    
    if (!email || !amount) {
        showToast("Please fill all fields", "error");
        return;
    }
    
    try {
        const txn = await apiRequest('/api/transactions/', {
            method: 'POST',
            body: JSON.stringify({ receiver_email: email, amount: amount })
        });
        showToast("Transaction created! Please provide biometric signature.", "success");
        document.getElementById('transfer-modal').style.display = 'none';
        
        await loadTransactions();
        
        // Auto-open biometric verification
        openVerifyModal(txn.id, 'sender');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function openVerifyModal(txnId, actionRole) {
    currentTxnId = txnId;
    currentTxnAction = actionRole;
    document.getElementById('face-verify-modal').style.display = 'flex';
    document.getElementById('txn-scan-btn').disabled = false;
    document.getElementById('txn-scan-btn').textContent = 'Start Scan';
    
    try {
        txnVideoStream = await navigator.mediaDevices.getUserMedia({ video: true });
        document.getElementById('txn-video').srcObject = txnVideoStream;
    } catch (err) {
        showToast("Camera access required for authorization", "error");
        closeFaceVerifyModal();
    }
}

function closeFaceVerifyModal() {
    document.getElementById('face-verify-modal').style.display = 'none';
    if (txnVideoStream) {
        txnVideoStream.getTracks().forEach(t => t.stop());
        txnVideoStream = null;
    }
}

async function executeTransactionScan() {
    const video = document.getElementById('txn-video');
    const btn = document.getElementById('txn-scan-btn');
    
    btn.disabled = true;
    btn.textContent = 'Scanning...';
    
    // Capture 3 frames rapidly
    const frames = [];
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    
    for (let i = 0; i < 3; i++) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        frames.push(canvas.toDataURL('image/jpeg', 0.8));
        await new Promise(r => setTimeout(r, 200));
    }
    
    try {
        btn.textContent = 'Verifying Integrity...';
        
        const endpoint = currentTxnAction === 'sender' 
            ? `/api/transactions/${currentTxnId}/verify-sender`
            : `/api/transactions/${currentTxnId}/verify-receiver`;
            
        await apiRequest(endpoint, {
            method: 'PATCH',
            body: JSON.stringify({ frames })
        });
        
        showToast("Biometric Signature Accepted!", "success");
        closeFaceVerifyModal();
        await loadTransactions();
        
    } catch (error) {
        showToast(error.message, "error");
        btn.disabled = false;
        btn.textContent = 'Retry Scan';
    }
}
