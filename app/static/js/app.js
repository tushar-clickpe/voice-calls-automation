/* Campaign Manager - Frontend JavaScript */

// ==========================================
// Campaign Actions (Start, Pause, Stop)
// ==========================================

async function campaignAction(campaignId, action) {
    const confirmActions = {
        stop: 'Are you sure you want to stop this campaign? In-progress contacts will be reset to pending.',
        pause: null,
        start: null,
    };

    if (confirmActions[action] && !confirm(confirmActions[action])) {
        return;
    }

    try {
        const response = await fetch(`/campaigns/${campaignId}/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        const data = await response.json();

        if (response.ok && data.success) {
            // Reload the page to reflect new state
            window.location.reload();
        } else {
            alert('Error: ' + (data.detail || data.error || 'Unknown error'));
        }
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function deleteCampaign(campaignId) {
    if (!confirm('Are you sure you want to delete this campaign and all its data? This cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch(`/campaigns/${campaignId}`, {
            method: 'DELETE',
        });

        if (response.ok) {
            window.location.href = '/campaigns';
        } else {
            const data = await response.json();
            alert('Error: ' + (data.detail || 'Failed to delete'));
        }
    } catch (e) {
        alert('Error: ' + e.message);
    }
}


// ==========================================
// Dashboard Polling
// ==========================================

let dashboardInterval = null;

function startDashboardPolling() {
    // Poll every 5 seconds
    dashboardInterval = setInterval(refreshDashboard, 5000);
}

async function refreshDashboard() {
    try {
        const response = await fetch('/api/stats/today');
        if (!response.ok) return;
        const data = await response.json();

        // Update global stats
        const gs = data.global_stats;
        updateText('gs-target', gs.target);
        updateText('gs-attempted', gs.attempted);
        updateText('gs-connected', gs.connected);
        updateText('gs-no-answer', gs.no_answer);
        updateText('gs-failed', gs.failed);

        const pct = gs.target > 0 ? (gs.attempted / gs.target * 100).toFixed(1) : 0;
        updateText('gs-pct', pct + '%');
        updateProgress('gs-progress', pct);

        // Update campaign cards
        data.campaigns.forEach(c => {
            const card = document.querySelector(`[data-campaign-id="${c.id}"]`);
            if (!card) return;

            // Update running state
            if (c.is_running) {
                card.classList.add('running');
            } else {
                card.classList.remove('running');
            }
        });

    } catch (e) {
        // Silent fail - will retry next interval
    }
}


// ==========================================
// Campaign Detail Polling
// ==========================================

let campaignInterval = null;

function startCampaignPolling(campaignId) {
    campaignInterval = setInterval(() => refreshCampaignDetail(campaignId), 5000);
}

async function refreshCampaignDetail(campaignId) {
    try {
        const response = await fetch(`/api/stats/campaign/${campaignId}`);
        if (!response.ok) return;
        const data = await response.json();

        // Update daily progress
        const d = data.daily;
        updateText('cd-attempted', d.attempted);
        updateText('cd-connected', d.connected);
        updateText('cd-no-answer', d.no_answer);
        updateText('cd-failed', d.failed);

        const pct = d.target > 0 ? (d.attempted / d.target * 100).toFixed(1) : 0;
        updateProgress('cd-progress', pct);

        // Update campaign stats
        const s = data.stats;
        updateText('cs-total', s.total || 0);
        updateText('cs-pending', s.pending || 0);
        updateText('cs-in-progress', s.in_progress || 0);
        updateText('cs-connected', s.connected || 0);
        updateText('cs-no-answer', s.no_answer || 0);
        updateText('cs-failed', s.failed || 0);
        updateText('cs-retries', s.retries_pending || 0);

        // Update recent activity
        if (data.recent_activity && data.recent_activity.length > 0) {
            const activityEl = document.getElementById('activity-list');
            if (activityEl) {
                let html = '<table class="table table-sm"><thead><tr>' +
                    '<th>Time</th><th>Phone</th><th>Name</th><th>Call Status</th><th>WhatsApp</th><th>Attempt</th>' +
                    '</tr></thead><tbody>';

                data.recent_activity.forEach(a => {
                    html += `<tr>
                        <td>${a.created_at}</td>
                        <td class="font-mono">${a.phone}</td>
                        <td>${a.contact_name || '-'}</td>
                        <td><span class="status-badge status-${a.contact_status}">${a.call_status || a.contact_status}</span></td>
                        <td>${a.whatsapp_status || '-'}</td>
                        <td>${a.attempt_number}</td>
                    </tr>`;
                });

                html += '</tbody></table>';
                activityEl.innerHTML = html;
            }
        }

    } catch (e) {
        // Silent fail
    }
}


// ==========================================
// Utility Functions
// ==========================================

function updateText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function updateProgress(id, percent) {
    const el = document.getElementById(id);
    if (el) el.style.width = Math.min(percent, 100) + '%';
}

// Cleanup intervals on page unload
window.addEventListener('beforeunload', () => {
    if (dashboardInterval) clearInterval(dashboardInterval);
    if (campaignInterval) clearInterval(campaignInterval);
});
