document.addEventListener('DOMContentLoaded', () => {
    fetchDashboardStats();
    fetchAutomations();
    fetchTimeline();
    checkSchedulerStatus();

    // Attach direct click listeners to nav items
    const navSettings = document.getElementById('nav-settings');
    if (navSettings) {
        navSettings.addEventListener('click', (e) => switchTab('settings', e));
    }
    const navDash = document.getElementById('nav-dashboard');
    if (navDash) {
        navDash.addEventListener('click', (e) => switchTab('dashboard', e));
    }
    const navAuto = document.getElementById('nav-automations');
    if (navAuto) {
        navAuto.addEventListener('click', (e) => switchTab('automations', e));
    }
    const navTimeline = document.getElementById('nav-timeline');
    if (navTimeline) {
        navTimeline.addEventListener('click', (e) => switchTab('timeline', e));
    }
    const navExec = document.getElementById('nav-executions');
    if (navExec) {
        navExec.addEventListener('click', (e) => switchTab('executions', e));
    }

    // Poll every 1 second for live simulation status & queue progress
    setInterval(() => {
        fetchDashboardStats();
        fetchAutomations();
        fetchTimeline();
        checkSchedulerStatus();
        if (activeTab === 'executions') {
            fetchExecutionHistory();
        }
    }, 1000);
});

let activeTab = 'dashboard';
window.allExecutions = [];
window.allTimelineEvents = [];
window.allAutomations = [];

function switchTab(tabName, event) {
    if (event && event.preventDefault) {
        event.preventDefault();
    }
    activeTab = tabName;
    
    // Update active class on nav links
    document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
    
    // Hide all views first
    document.querySelectorAll('.tab-view').forEach(el => {
        el.style.display = 'none';
        el.classList.remove('active');
    });
    
    if (tabName === 'automations') {
        const navAuto = document.getElementById('nav-automations');
        if (navAuto) navAuto.classList.add('active');
        const viewAuto = document.getElementById('view-automations');
        if (viewAuto) {
            viewAuto.style.display = 'grid';
            viewAuto.classList.add('active');
        }
        fetchAutomations();
    } else if (tabName === 'timeline') {
        const navTimeline = document.getElementById('nav-timeline');
        if (navTimeline) navTimeline.classList.add('active');
        const viewTimeline = document.getElementById('view-timeline');
        if (viewTimeline) {
            viewTimeline.style.display = 'grid';
            viewTimeline.classList.add('active');
        }
        fetchTimeline();
    } else if (tabName === 'executions') {
        const navExec = document.getElementById('nav-executions');
        if (navExec) navExec.classList.add('active');
        const viewExec = document.getElementById('view-executions');
        if (viewExec) {
            viewExec.style.display = 'grid';
            viewExec.classList.add('active');
        }
        fetchExecutionHistory();
    } else if (tabName === 'settings') {
        const navSettings = document.getElementById('nav-settings');
        if (navSettings) navSettings.classList.add('active');
        const viewSettings = document.getElementById('view-settings');
        if (viewSettings) {
            viewSettings.style.display = 'grid';
            viewSettings.classList.add('active');
        }
        fetchSettings();
    } else {
        const navDash = document.getElementById('nav-dashboard');
        if (navDash) navDash.classList.add('active');
        const viewDash = document.getElementById('view-dashboard');
        if (viewDash) {
            viewDash.style.display = 'grid';
            viewDash.classList.add('active');
        }
    }
}

async function fetchDashboardStats() {
    try {
        const res = await fetch('/api/dashboard/stats');
        const data = await res.json();
        if (!data.ok) return;

        const m = data.metrics;
        document.getElementById('completed-num').innerText = m.completed;
        document.getElementById('running-num').innerText = m.running;
        const retrialEl = document.getElementById('retrial-num');
        if (retrialEl) retrialEl.innerText = m.retrial;
        document.getElementById('waiting-num').innerText = m.waiting;
        document.getElementById('failed-num').innerText = m.failed;

        document.getElementById('completed-bar').style.width = m.rates.success;
        document.getElementById('running-bar').style.width = m.rates.running;
        const retrialBar = document.getElementById('retrial-bar');
        if (retrialBar) retrialBar.style.width = m.rates.retrial;
        document.getElementById('waiting-bar').style.width = m.rates.waiting;
        document.getElementById('failed-bar').style.width = m.rates.failure;

        document.getElementById('clock-time').innerText = data.time;
        const clockDateEl = document.getElementById('clock-date');
        if (clockDateEl && data.date) clockDateEl.innerText = data.date;

        const simBadge = document.getElementById('sim-badge');
        if (simBadge) {
            if (data.sim_mode && data.sim_speed && data.sim_speed !== 'Realtime') {
                simBadge.textContent = `⚡ ${data.sim_speed}`;
                simBadge.style.background = 'rgba(96, 165, 250, 0.15)';
                simBadge.style.color = '#60a5fa';
                simBadge.style.borderColor = 'rgba(96, 165, 250, 0.3)';
            } else {
                simBadge.textContent = '⏱ Realtime';
                simBadge.style.background = 'rgba(52, 211, 153, 0.15)';
                simBadge.style.color = '#34d399';
                simBadge.style.borderColor = 'rgba(52, 211, 153, 0.3)';
            }
        }

        const sysExec = document.getElementById('sys-status-execution');
        if (sysExec) {
            if (m.running > 0) {
                sysExec.innerHTML = `● Execution Service: Running (${m.running})`;
                sysExec.style.color = '#60a5fa';
            } else {
                sysExec.innerHTML = '✓ Execution Service: Idle';
                sysExec.style.color = 'var(--text-muted)';
            }
        }
    } catch (e) {
        console.error('Stats poll failed:', e);
    }
}

async function checkSchedulerStatus() {
    try {
        const res = await fetch('/api/paradiso/status');
        const data = await res.json();
        const startBtn = document.getElementById('btn-start-scheduler');
        const sysScheduler = document.getElementById('sys-status-scheduler');

        if (data.ok && data.running) {
            startBtn.classList.add('btn-start-active');
            startBtn.innerHTML = '● Scheduler Running';
            if (sysScheduler) {
                sysScheduler.innerHTML = '✓ Scheduler: Active';
                sysScheduler.style.color = '#34d399';
            }
        } else {
            startBtn.classList.remove('btn-start-active');
            startBtn.innerHTML = 'Start Scheduler';
            if (sysScheduler) {
                sysScheduler.innerHTML = '○ Scheduler: Standby';
                sysScheduler.style.color = 'var(--text-muted)';
            }
        }
    } catch (e) {}
}

function formatTime12(timeStr) {
    if (!timeStr || timeStr === '--') return '--';
    if (timeStr.includes('AM') || timeStr.includes('PM') || timeStr.includes('am') || timeStr.includes('pm')) return timeStr;
    const parts = timeStr.split(':');
    if (parts.length < 2) return timeStr;
    let hours = parseInt(parts[0], 10);
    const minutes = parts[1].substring(0, 2);
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    const strHours = hours < 10 ? '0' + hours : hours;
    return `${strHours}:${minutes} ${ampm}`;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function fetchAutomations() {
    try {
        const res = await fetch('/api/automations');
        const data = await res.json();
        if (!data.ok) return;

        window.allAutomations = data.automations || [];

        const tbody = document.getElementById('automations-body');
        if (tbody) {
            tbody.innerHTML = '';
            data.automations.forEach((item, index) => {
                const tr = document.createElement('tr');

                let badgeClass = 'badge-waiting';
                let execModeHtml = `<span style="font-size: 11px; color: var(--text-muted); padding: 3px 8px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 4px;">Sequential (Type A)</span>`;

                if (item.status === 'Completed') {
                    badgeClass = 'badge-completed';
                } else if (item.status === 'Running') {
                    badgeClass = 'badge-running';
                    execModeHtml = `<span style="display: inline-flex; align-items: center; font-size: 11px; color: #60a5fa; font-weight: 600; padding: 3px 8px; background: rgba(96, 165, 250, 0.1); border: 1px solid rgba(96, 165, 250, 0.25); border-radius: 4px;"><span class="spinner"></span> Executing</span>`;
                } else if (item.status === 'Retrial') {
                    badgeClass = 'badge-retrial';
                } else if (item.status === 'Failed') {
                    badgeClass = 'badge-failed';
                }

                tr.innerHTML = `
                    <td>${index + 1}</td>
                    <td><strong>${escapeHtml(item.name)}</strong></td>
                    <td>${escapeHtml(item.team)}</td>
                    <td>${escapeHtml(formatTime12(item.scheduled_time))}</td>
                    <td><span class="badge ${badgeClass}">${escapeHtml(item.status)}</span></td>
                    <td>${escapeHtml(item.duration)}</td>
                    <td>${escapeHtml(formatTime12(item.started_at))}</td>
                    <td>${execModeHtml}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        filterAutomationsCatalog();
    } catch (e) {
        console.error('Automations poll failed:', e);
    }
}

function filterAutomationsCatalog() {
    const rawList = window.allAutomations || [];

    // Calculate Summary Metrics
    const totalEl = document.getElementById('stat-auto-total');
    const waitingEl = document.getElementById('stat-auto-waiting');
    const pyEl = document.getElementById('stat-auto-python');
    const rEl = document.getElementById('stat-auto-rscript');

    let totalCount = rawList.length;
    let waitingCount = 0;
    let pyCount = 0;
    let rCount = 0;

    rawList.forEach(r => {
        const s = (r.status || '').toLowerCase();
        if (s === 'waiting' || s === 'running' || s === 'retrial') waitingCount++;
        const ft = (r.filetype || '').toLowerCase();
        if (ft.includes('py') || ft.includes('python')) pyCount++;
        else if (ft.includes('r')) rCount++;
    });

    if (totalEl) totalEl.innerText = totalCount;
    if (waitingEl) waitingEl.innerText = waitingCount;
    if (pyEl) pyEl.innerText = pyCount;
    if (rEl) rEl.innerText = rCount;

    // Dynamically populate Team Filter if needed
    const teamSelect = document.getElementById('auto-team-filter');
    if (teamSelect && teamSelect.options.length <= 1) {
        const teams = [...new Set(rawList.map(r => r.team).filter(Boolean))].sort();
        teams.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.innerText = t;
            teamSelect.appendChild(opt);
        });
    }

    const grid = document.getElementById('automations-catalog-grid');
    if (!grid) return;

    const searchInput = document.getElementById('auto-catalog-search');
    const runtimeSelect = document.getElementById('auto-runtime-filter');
    const statusSelect = document.getElementById('auto-status-filter');

    const searchVal = (searchInput ? searchInput.value : '').toLowerCase().trim();
    const teamVal = teamSelect ? teamSelect.value : 'ALL';
    const runtimeVal = runtimeSelect ? runtimeSelect.value : 'ALL';
    const statusVal = statusSelect ? statusSelect.value : 'ALL';
    const matchCountEl = document.getElementById('auto-match-count');

    const filtered = rawList.filter(item => {
        if (teamVal !== 'ALL' && (item.team || '') !== teamVal) return false;
        
        if (runtimeVal !== 'ALL') {
            const ft = (item.filetype || '').toLowerCase();
            if (runtimeVal === 'python' && !ft.includes('py')) return false;
            if (runtimeVal === 'R' && !ft.includes('r')) return false;
        }

        if (statusVal !== 'ALL') {
            const s = (item.status || '');
            if (statusVal === 'Inactive') {
                if (s !== 'Inactive' && s !== 'Disabled') return false;
            } else {
                if (s !== statusVal) return false;
            }
        }

        if (searchVal) {
            const name = (item.name || '').toLowerCase();
            const fn = (item.filename || '').toLowerCase();
            const owner = (item.owner || '').toLowerCase();
            const team = (item.team || '').toLowerCase();
            return name.includes(searchVal) || fn.includes(searchVal) || owner.includes(searchVal) || team.includes(searchVal);
        }

        return true;
    });

    if (matchCountEl) {
        matchCountEl.innerText = `Showing ${filtered.length} of ${totalCount} reports`;
    }

    grid.innerHTML = '';

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div class="timeline-empty-state" style="grid-column: 1 / -1;">
                <div style="font-size: 24px; margin-bottom: 8px;">📑</div>
                <div style="font-size: 14px; font-weight: 600; color: #cbd5e1;">No Automation Reports Found</div>
                <div style="font-size: 12px; margin-top: 4px;">Try adjusting your search criteria or register a new report above.</div>
            </div>
        `;
        return;
    }

    filtered.forEach(item => {
        let badgeClass = 'badge-waiting';
        if (item.status === 'Completed') badgeClass = 'badge-completed';
        else if (item.status === 'Running') badgeClass = 'badge-running';
        else if (item.status === 'Retrial') badgeClass = 'badge-retrial';
        else if (item.status === 'Failed') badgeClass = 'badge-failed';

        const isPython = (item.filetype || '').toLowerCase().includes('py');
        const runtimeBadgeClass = isPython ? 'badge-runtime-python' : 'badge-runtime-rscript';
        const runtimeLabel = isPython ? 'Python' : 'Rscript';

        const card = document.createElement('div');
        card.className = 'automation-card';
        card.innerHTML = `
            <div>
                <div class="automation-card-top">
                    <div>
                        <div class="automation-card-title">${escapeHtml(item.name)}</div>
                        <div class="automation-card-team">🏢 ${escapeHtml(item.team || 'General')}</div>
                    </div>
                    <span class="badge ${badgeClass}">${escapeHtml(item.status)}</span>
                </div>

                <div class="automation-card-meta">
                    <div class="automation-meta-row">
                        <span class="automation-meta-label">Schedule:</span>
                        <span class="automation-meta-val">⏱ ${escapeHtml(formatTime12(item.scheduled_time))}</span>
                    </div>
                    <div class="automation-meta-row">
                        <span class="automation-meta-label">Runtime:</span>
                        <span class="${runtimeBadgeClass}">${runtimeLabel}</span>
                    </div>
                    <div class="automation-meta-row">
                        <span class="automation-meta-label">Script:</span>
                        <span class="automation-meta-val" style="font-size: 11px;">${escapeHtml(item.dir || '../reports')}/${escapeHtml(item.filename)}</span>
                    </div>
                    <div class="automation-meta-row">
                        <span class="automation-meta-label">Owner:</span>
                        <span class="automation-meta-val">${escapeHtml(item.owner || 'System')}</span>
                    </div>
                </div>
            </div>

            <div class="automation-card-actions">
                <span style="font-size: 11px; color: var(--text-muted);">Last: ${escapeHtml(item.last_run || '--')}</span>
                <button type="button" class="btn-card-action" onclick="deleteReport('${escapeHtml(item.name)}')" title="Delete report from catalog">
                    🗑 Delete
                </button>
            </div>
        `;
        grid.appendChild(card);
    });
}

function openAddReportModal() {
    const modal = document.getElementById('modal-add-report');
    if (!modal) return;
    const form = document.getElementById('form-add-report');
    if (form) form.reset();
    const err = document.getElementById('add-report-error');
    if (err) {
        err.style.display = 'none';
        err.innerText = '';
    }
    const dirInput = document.getElementById('new-report-dir');
    if (dirInput) dirInput.value = '../reports';
    const teamInput = document.getElementById('new-report-team');
    if (teamInput) teamInput.value = 'General';
    const ownerInput = document.getElementById('new-report-owner');
    if (ownerInput) ownerInput.value = 'User';
    const timeInput = document.getElementById('new-report-time');
    if (timeInput) timeInput.value = '08:30';
    const statusSelect = document.getElementById('new-report-status');
    if (statusSelect) statusSelect.value = 'Waiting';

    modal.classList.add('active');
}

function closeAddReportModal() {
    const modal = document.getElementById('modal-add-report');
    if (modal) modal.classList.remove('active');
}

function handleAddModalOverlayClick(e) {
    if (e.target && e.target.id === 'modal-add-report') {
        closeAddReportModal();
    }
}

async function handleAddReportSubmit(e) {
    e.preventDefault();
    const errEl = document.getElementById('add-report-error');
    const btn = document.getElementById('btn-submit-add-report');
    const origText = btn.innerText;

    const name = (document.getElementById('new-report-name').value || '').trim();
    const filename = (document.getElementById('new-report-filename').value || '').trim();
    const filetype = document.getElementById('new-report-filetype').value;
    const dir = (document.getElementById('new-report-dir').value || '../reports').trim();
    const team = (document.getElementById('new-report-team').value || 'General').trim();
    const owner = (document.getElementById('new-report-owner').value || 'User').trim();
    const scheduled_time = (document.getElementById('new-report-time').value || '08:30').trim();
    const status = document.getElementById('new-report-status').value;

    if (!name || !filename) {
        if (errEl) {
            errEl.innerText = 'Report name and filename are required.';
            errEl.style.display = 'block';
        }
        return;
    }

    btn.disabled = true;
    btn.innerText = '⏳ Registering...';

    try {
        const res = await fetch('/api/automation/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                filename,
                filetype,
                dir,
                team,
                owner,
                scheduled_time,
                status
            })
        });
        const data = await res.json();
        if (data.ok) {
            closeAddReportModal();
            showSettingsToast(data.message || `Report '${name}' registered successfully!`, 'success');
            await fetchAutomations();
            await fetchDashboardStats();
        } else {
            if (errEl) {
                errEl.innerText = data.error || 'Failed to add report.';
                errEl.style.display = 'block';
            }
        }
    } catch (err) {
        console.error('Add report error:', err);
        if (errEl) {
            errEl.innerText = 'Network error while registering report.';
            errEl.style.display = 'block';
        }
    } finally {
        btn.disabled = false;
        btn.innerText = origText;
    }
}

async function deleteReport(name) {
    if (!confirm(`Are you sure you want to delete report '${name}'? This will remove it from the catalog and today's queue.`)) {
        return;
    }

    try {
        const res = await fetch(`/api/automation/delete/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (data.ok) {
            showSettingsToast(data.message || `Report '${name}' deleted successfully.`, 'success');
            await fetchAutomations();
            await fetchDashboardStats();
        } else {
            showSettingsToast(data.error || 'Failed to delete report.', 'error');
        }
    } catch (e) {
        console.error('Delete report error:', e);
        showSettingsToast('Network error deleting report.', 'error');
    }
}

async function fetchTimeline() {
    try {
        const res = await fetch('/api/dashboard/timeline');
        const data = await res.json();
        if (!data.ok) return;

        window.allTimelineEvents = data.timeline || [];

        const list = document.getElementById('timeline-list');
        const countLabel = document.getElementById('timeline-count-label');
        if (countLabel) countLabel.innerText = `(${data.timeline.length})`;
        
        if (list) {
            list.innerHTML = '';
            // Render newest timeline events at top
            const sorted = [...data.timeline].reverse();
            sorted.slice(0, 30).forEach(t => {
                const div = document.createElement('div');
                const safeType = ['system', 'start', 'success', 'fail', 'waiting', 'retrial'].includes(t.type) ? t.type : 'system';
                div.className = `timeline-item event-${safeType}`;
                div.innerHTML = `
                    <div class="timeline-time">${escapeHtml(t.timestamp)}</div>
                    <div class="timeline-content">
                        <strong>${escapeHtml(t.title)}</strong><br>
                        <span style="color: var(--text-muted);">${escapeHtml(t.description)}</span>
                    </div>
                `;
                list.appendChild(div);
            });
        }

        // Always update expanded timeline if it exists
        filterTimelineEvents();
    } catch (e) {
        console.error('Timeline poll failed:', e);
    }
}

let timelineCurrentPage = 1;
let timelinePageSize = 50;
window._lastFilteredTimelineCount = 0;

function onTimelineFilterChange() {
    timelineCurrentPage = 1;
    filterTimelineEvents();
}

function onTimelinePageSizeChange() {
    const el = document.getElementById('timeline-pagesize-filter');
    if (!el) return;
    const val = el.value;
    timelinePageSize = val === 'ALL' ? Infinity : (parseInt(val, 10) || 50);
    timelineCurrentPage = 1;
    filterTimelineEvents();
}

function goToTimelinePage(page) {
    const pageSize = timelinePageSize === Infinity ? (window._lastFilteredTimelineCount || 1) : timelinePageSize;
    const totalPages = Math.max(1, Math.ceil((window._lastFilteredTimelineCount || 0) / pageSize));
    if (page === 'last') {
        timelineCurrentPage = totalPages;
    } else {
        timelineCurrentPage = Math.max(1, Math.min(page, totalPages));
    }
    filterTimelineEvents();
    const container = document.getElementById('view-timeline');
    if (container) {
        container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function changeTimelinePage(delta) {
    goToTimelinePage(timelineCurrentPage + delta);
}

function filterTimelineEvents() {
    const rawEvents = window.allTimelineEvents || [];
    
    // Update summary stat numbers on expanded page
    const totalEl = document.getElementById('stat-timeline-total');
    const systemEl = document.getElementById('stat-timeline-system');
    const successEl = document.getElementById('stat-timeline-success');
    const alertsEl = document.getElementById('stat-timeline-alerts');
    const badgeEl = document.getElementById('expanded-timeline-badge');

    let totalCount = rawEvents.length;
    let systemCount = 0;
    let successCount = 0;
    let alertsCount = 0;

    rawEvents.forEach(e => {
        const type = (e.type || '').toLowerCase();
        if (type === 'system' || type === 'start') systemCount++;
        else if (type === 'success' || type === 'completed') successCount++;
        else if (type === 'fail' || type === 'failed' || type === 'retrial') alertsCount++;
    });

    if (totalEl) totalEl.innerText = totalCount;
    if (systemEl) systemEl.innerText = systemCount;
    if (successEl) successEl.innerText = successCount;
    if (alertsEl) alertsEl.innerText = alertsCount;
    if (badgeEl) badgeEl.innerText = `${totalCount} Events`;

    const container = document.getElementById('expanded-timeline-list');
    if (!container) return;

    const searchInput = document.getElementById('timeline-search');
    const typeSelect = document.getElementById('timeline-type-filter');
    const orderSelect = document.getElementById('timeline-order-filter');
    const searchVal = (searchInput ? searchInput.value : '').toLowerCase().trim();
    const typeVal = typeSelect ? typeSelect.value : 'ALL';
    const orderVal = orderSelect ? orderSelect.value : 'newest';
    const matchCountEl = document.getElementById('timeline-match-count');

    // Filter events
    let filtered = rawEvents.filter(item => {
        const itemType = (item.type || 'system').toLowerCase();
        // Type matching
        let matchesType = true;
        if (typeVal === 'system') {
            matchesType = (itemType === 'system');
        } else if (typeVal === 'start') {
            matchesType = (itemType === 'start');
        } else if (typeVal === 'success') {
            matchesType = (itemType === 'success' || itemType === 'completed');
        } else if (typeVal === 'fail') {
            matchesType = (itemType === 'fail' || itemType === 'failed');
        } else if (typeVal === 'retrial') {
            matchesType = (itemType === 'retrial');
        }

        if (!matchesType) return false;

        // Search matching
        if (searchVal) {
            const title = (item.title || '').toLowerCase();
            const desc = (item.description || '').toLowerCase();
            const time = (item.timestamp || '').toLowerCase();
            return title.includes(searchVal) || desc.includes(searchVal) || time.includes(searchVal);
        }
        return true;
    });

    // Sorting
    if (orderVal === 'newest') {
        filtered = [...filtered].reverse();
    }

    window._lastFilteredTimelineCount = filtered.length;

    // Pagination calculations
    const pageSize = timelinePageSize === Infinity ? (filtered.length || 1) : timelinePageSize;
    const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
    if (timelineCurrentPage > totalPages) {
        timelineCurrentPage = totalPages;
    }
    if (timelineCurrentPage < 1) {
        timelineCurrentPage = 1;
    }

    const startIndex = (timelineCurrentPage - 1) * pageSize;
    const endIndex = Math.min(startIndex + pageSize, filtered.length);
    const pageItems = filtered.slice(startIndex, endIndex);

    if (matchCountEl) {
        if (filtered.length === 0) {
            matchCountEl.innerText = `Showing 0 of ${totalCount} events`;
        } else {
            matchCountEl.innerText = `Showing ${startIndex + 1}–${endIndex} of ${filtered.length} events`;
        }
    }

    container.innerHTML = '';

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="timeline-empty-state">
                <div style="font-size: 24px; margin-bottom: 8px;">🕊</div>
                <div style="font-size: 14px; font-weight: 600; color: #cbd5e1;">No Timeline Events Found</div>
                <div style="font-size: 12px; margin-top: 4px;">Try adjusting your search query or category filter.</div>
            </div>
        `;
        renderTimelinePagination(0, 0, 0, 1);
        return;
    }

    pageItems.forEach(t => {
        const rawType = (t.type || 'system').toLowerCase();
        const safeType = ['system', 'start', 'success', 'fail', 'failed', 'waiting', 'retrial'].includes(rawType) ? rawType : 'system';
        const card = document.createElement('div');
        card.className = `expanded-timeline-item event-${safeType}`;

        let icon = '●';
        let badgeLabel = 'System';
        if (safeType === 'success' || safeType === 'completed') {
            icon = '✓';
            badgeLabel = 'Completed';
        } else if (safeType === 'fail' || safeType === 'failed') {
            icon = '✕';
            badgeLabel = 'Failed';
        } else if (safeType === 'start') {
            icon = '⚡';
            badgeLabel = 'Initiated';
        } else if (safeType === 'retrial') {
            icon = '↻';
            badgeLabel = 'Retrial';
        } else if (safeType === 'waiting') {
            icon = '○';
            badgeLabel = 'Waiting';
        }

        card.innerHTML = `
            <div class="expanded-timeline-accent"></div>
            <div class="expanded-timeline-body">
                <div class="expanded-timeline-header">
                    <div class="expanded-timeline-title">
                        <span style="font-size: 12px;">${icon}</span>
                        <span>${escapeHtml(t.title)}</span>
                    </div>
                    <div class="expanded-timeline-meta">
                        <span class="expanded-timeline-badge badge-${safeType}">${badgeLabel}</span>
                        <span class="expanded-timeline-time">⏱ ${escapeHtml(t.timestamp)}</span>
                    </div>
                </div>
                <div class="expanded-timeline-desc">${escapeHtml(t.description)}</div>
            </div>
        `;
        container.appendChild(card);
    });

    renderTimelinePagination(filtered.length, startIndex + 1, endIndex, totalPages);
}

function renderTimelinePagination(totalItems, start, end, totalPages) {
    const bar = document.getElementById('timeline-pagination-bar');
    if (!bar) return;

    if (totalItems <= 0 || timelinePageSize === Infinity || totalPages <= 1) {
        bar.style.display = 'none';
        return;
    }

    bar.style.display = 'flex';

    const infoEl = document.getElementById('timeline-pagination-info');
    if (infoEl) {
        infoEl.innerText = `Showing ${start}–${end} of ${totalItems} events (Page ${timelineCurrentPage} of ${totalPages})`;
    }

    const btnFirst = document.getElementById('btn-page-first');
    const btnPrev = document.getElementById('btn-page-prev');
    const btnNext = document.getElementById('btn-page-next');
    const btnLast = document.getElementById('btn-page-last');

    if (btnFirst) btnFirst.disabled = (timelineCurrentPage <= 1);
    if (btnPrev) btnPrev.disabled = (timelineCurrentPage <= 1);
    if (btnNext) btnNext.disabled = (timelineCurrentPage >= totalPages);
    if (btnLast) btnLast.disabled = (timelineCurrentPage >= totalPages);

    const pageNumbersContainer = document.getElementById('timeline-page-numbers');
    if (!pageNumbersContainer) return;
    pageNumbersContainer.innerHTML = '';

    // Calculate pages to show: maximum 7 page buttons with ellipsis
    let pages = [];
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        if (timelineCurrentPage > 3) {
            pages.push('...');
        }
        const startP = Math.max(2, timelineCurrentPage - 1);
        const endP = Math.min(totalPages - 1, timelineCurrentPage + 1);
        for (let i = startP; i <= endP; i++) {
            if (!pages.includes(i)) pages.push(i);
        }
        if (timelineCurrentPage < totalPages - 2) {
            pages.push('...');
        }
        if (!pages.includes(totalPages)) {
            pages.push(totalPages);
        }
    }

    pages.forEach(p => {
        if (p === '...') {
            const span = document.createElement('span');
            span.className = 'pagination-ellipsis';
            span.innerText = '…';
            pageNumbersContainer.appendChild(span);
        } else {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `btn-page-num ${p === timelineCurrentPage ? 'active' : ''}`;
            btn.innerText = p;
            btn.onclick = () => goToTimelinePage(p);
            pageNumbersContainer.appendChild(btn);
        }
    });
}

async function fetchExecutionHistory() {
    try {
        const res = await fetch('/api/executions/history');
        const data = await res.json();
        if (!data.ok) return;

        window.allExecutions = data.history || [];
        filterExecutions();
    } catch (e) {
        console.error('Failed to fetch execution history:', e);
    }
}

function filterExecutions() {
    const searchInput = document.getElementById('exec-search');
    const statusSelect = document.getElementById('exec-status-filter');
    const searchVal = (searchInput ? searchInput.value : '').toLowerCase().trim();
    const statusVal = statusSelect ? statusSelect.value : 'ALL';

    const filtered = window.allExecutions.filter(item => {
        const matchesName = item.report_name.toLowerCase().includes(searchVal);
        let matchesStatus = true;
        if (statusVal === 'Completed') matchesStatus = item.status === 'Completed';
        else if (statusVal === 'Retrial') matchesStatus = item.status === 'Retrial';
        else if (statusVal === 'Failed') matchesStatus = item.status === 'Failed';
        else if (statusVal === 'Skipped') matchesStatus = (item.status === 'Skipped' || item.status === 'Rotated');
        
        return matchesName && matchesStatus;
    });

    renderExecutionsTable(filtered);
}

function renderExecutionsTable(items) {
    const tbody = document.getElementById('executions-history-body');
    const label = document.getElementById('exec-count-label');
    if (label) label.innerText = `${items.length} recorded execution${items.length === 1 ? '' : 's'}`;

    if (!tbody) return;
    tbody.innerHTML = '';

    if (items.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">
                    No execution logs found matching criteria.
                </td>
            </tr>
        `;
        return;
    }

    items.forEach((item, index) => {
        const tr = document.createElement('tr');

        let badgeClass = 'badge-completed';
        if (item.status === 'Failed') badgeClass = 'badge-failed';
        else if (item.status === 'Retrial') badgeClass = 'badge-retrial';
        else if (item.status === 'Skipped' || item.status === 'Rotated') badgeClass = 'badge-waiting';

        tr.innerHTML = `
            <td>${index + 1}</td>
            <td>${escapeHtml(item.date)}</td>
            <td><strong>${escapeHtml(item.report_name)}</strong></td>
            <td>${escapeHtml(item.started_at)}</td>
            <td>${escapeHtml(item.finished_at)}</td>
            <td>${escapeHtml(item.duration)}</td>
            <td><span class="badge ${badgeClass}">${escapeHtml(item.status)}</span></td>
            <td>
                <button class="btn-action btn-view-log">📜 View Log</button>
            </td>
        `;
        const btn = tr.querySelector('.btn-view-log');
        if (btn) {
            btn.addEventListener('click', () => openLogModal(item.report_name));
        }
        tbody.appendChild(tr);
    });
}

async function openLogModal(reportName) {
    const modal = document.getElementById('modal-log-viewer');
    const title = document.getElementById('modal-log-title');
    const status = document.getElementById('modal-log-status');
    const duration = document.getElementById('modal-log-duration');
    const lastrun = document.getElementById('modal-log-lastrun');
    const content = document.getElementById('modal-log-content');

    if (!modal) return;
    title.innerText = `Console Log — ${reportName}`;
    content.innerText = 'Loading console stream output...';
    modal.classList.add('active');

    try {
        const res = await fetch(`/api/executions/log/${reportName}`);
        const data = await res.json();
        if (data.ok && data.log) {
            const l = data.log;
            status.innerText = l.status || 'Completed';
            
            if (l.status === 'Completed') status.className = 'badge badge-completed';
            else if (l.status === 'Failed') status.className = 'badge badge-failed';
            else status.className = 'badge badge-waiting';

            duration.innerText = l.duration || '--';
            lastrun.innerText = l.last_run || '--';
            content.innerText = typeof l.last_output === 'string' ? l.last_output : JSON.stringify(l.last_output, null, 2);
        } else {
            content.innerText = `No active log output file found for '${reportName}'.`;
        }
    } catch (e) {
        content.innerText = `Error fetching console log: ${e.message}`;
    }
}

function closeLogModal() {
    const modal = document.getElementById('modal-log-viewer');
    if (modal) modal.classList.remove('active');
}

function handleModalOverlayClick(e) {
    if (e.target && e.target.id === 'modal-log-viewer') {
        closeLogModal();
    }
}

async function runReport(name) {
    try {
        const res = await fetch('/api/automation/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await res.json();
        fetchAutomations();
    } catch (e) {
        console.error('Failed to trigger report run:', e);
    }
}

async function startScheduler() {
    await fetch('/api/paradiso/start', { method: 'POST' });
    checkSchedulerStatus();
    fetchAutomations();
}

async function stopScheduler() {
    await fetch('/api/paradiso/stop', { method: 'POST' });
    checkSchedulerStatus();
    fetchAutomations();
}

async function resetAutomations() {
    try {
        await fetch('/api/automations/reset', { method: 'POST' });
        fetchAutomations();
        fetchDashboardStats();
        fetchTimeline();
        if (activeTab === 'executions') {
            fetchExecutionHistory();
        }
    } catch (e) {
        console.error('Failed to reset automations:', e);
    }
}

// ==========================================================================
// Settings Subsystem Functions
// ==========================================================================

async function fetchSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        if (!data.ok || !data.settings) return;

        const s = data.settings;
        const sched = s.scheduler || {};
        const sim = s.simulation || {};
        const exec = s.executables || {};
        const log = s.logging || {};
        const meta = s.runtime_meta || {};

        // Scheduler fields
        const autoStartEl = document.getElementById('setting-auto-start');
        if (autoStartEl) autoStartEl.value = sched.auto_start ? "true" : "false";

        const startEl = document.getElementById('setting-start-time');
        if (startEl) startEl.value = sched.intraday_start_time || "07:00";

        const idleEl = document.getElementById('setting-idle-time');
        if (idleEl) idleEl.value = sched.intraday_idle_time || "21:00";

        const closeEl = document.getElementById('setting-close-time');
        if (closeEl) closeEl.value = sched.intraday_close_time || "22:00";

        const jobIntEl = document.getElementById('setting-job-interval');
        if (jobIntEl) jobIntEl.value = sched.job_interval_seconds || 15;

        // Simulation fields
        const simEnabledEl = document.getElementById('setting-sim-enabled');
        if (simEnabledEl) simEnabledEl.value = sim.enabled ? "true" : "false";

        const simSpeedEl = document.getElementById('setting-sim-speed');
        if (simSpeedEl) simSpeedEl.value = parseFloat(sim.speed_multiplier || 600.0).toFixed(1);

        toggleSimSpeedDisabled();

        // Executable fields
        const pyPathEl = document.getElementById('setting-python-path');
        if (pyPathEl) pyPathEl.value = exec.python_path || "";
        const pyHint = document.getElementById('hint-detected-python');
        if (pyHint && meta.detected_python) {
            pyHint.innerText = `Active system Python: ${meta.detected_python}`;
        }

        const rPathEl = document.getElementById('setting-rscript-path');
        if (rPathEl) rPathEl.value = exec.rscript_path || "";
        const rHint = document.getElementById('hint-detected-rscript');
        if (rHint && meta.detected_rscript) {
            rHint.innerText = `Detected in PATH: ${meta.detected_rscript}`;
        }

        // Logging fields
        const logLevelEl = document.getElementById('setting-log-level');
        if (logLevelEl) logLevelEl.value = (log.level || "INFO").toUpperCase();

        const logDirEl = document.getElementById('setting-log-dir');
        if (logDirEl) logDirEl.value = log.dir || "logs";

        // Storage paths info
        const storageAuto = document.getElementById('info-storage-automations');
        if (storageAuto && s.storage) storageAuto.innerText = s.storage.automations_file || "storage/automations.json";
        const storageIntra = document.getElementById('info-storage-intraday');
        if (storageIntra && s.storage) storageIntra.innerText = s.storage.intraday_file || "storage/intraday.json";

    } catch (e) {
        console.error('Failed to fetch settings:', e);
        showSettingsToast('Failed to load settings from server.', 'error');
    }
}

function toggleSimSpeedDisabled() {
    const simEnabled = document.getElementById('setting-sim-enabled');
    const simSpeed = document.getElementById('setting-sim-speed');
    if (simEnabled && simSpeed) {
        simSpeed.disabled = simEnabled.value !== 'true';
    }
}

async function handleSettingsSubmit(e) {
    e.preventDefault();
    const btn = document.getElementById('btn-save-settings');
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = '⏳ Saving...';

    const payload = {
        scheduler: {
            auto_start: document.getElementById('setting-auto-start').value === 'true',
            intraday_start_time: document.getElementById('setting-start-time').value.trim(),
            intraday_idle_time: document.getElementById('setting-idle-time').value.trim(),
            intraday_close_time: document.getElementById('setting-close-time').value.trim(),
            job_interval_seconds: parseInt(document.getElementById('setting-job-interval').value, 10) || 15
        },
        simulation: {
            enabled: document.getElementById('setting-sim-enabled').value === 'true',
            speed_multiplier: parseFloat(document.getElementById('setting-sim-speed').value) || 600.0
        },
        executables: {
            python_path: document.getElementById('setting-python-path').value.trim(),
            rscript_path: document.getElementById('setting-rscript-path').value.trim()
        },
        logging: {
            level: document.getElementById('setting-log-level').value,
            dir: document.getElementById('setting-log-dir').value.trim() || 'logs'
        }
    };

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.ok) {
            showSettingsToast(data.message || 'Settings saved and applied successfully!', 'success');
            fetchDashboardStats();
        } else {
            showSettingsToast(data.error || 'Failed to save settings.', 'error');
        }
    } catch (err) {
        console.error('Error saving settings:', err);
        showSettingsToast('Network error while saving settings.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

async function triggerClockReset() {
    try {
        const res = await fetch('/api/settings/simulation/reset', { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
            showSettingsToast('Simulation clock reset to midnight.', 'success');
            fetchDashboardStats();
            fetchTimeline();
        }
    } catch (e) {
        console.error('Error resetting clock:', e);
        showSettingsToast('Failed to reset simulation clock.', 'error');
    }
}

function showSettingsToast(msg, type = 'success') {
    const banner = document.getElementById('settings-alert-banner');
    if (!banner) return;
    banner.className = `settings-toast ${type === 'success' ? 'toast-success' : 'toast-error'}`;
    banner.innerText = (type === 'success' ? '✓ ' : '⚠ ') + msg;
    banner.style.display = 'flex';
    clearTimeout(window._toastTimeout);
    window._toastTimeout = setTimeout(() => {
        banner.style.display = 'none';
    }, 4000);
}

