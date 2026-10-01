document.addEventListener('DOMContentLoaded', () => {
    fetchDashboardStats();
    fetchAutomations();
    fetchTimeline();
    fetchLanesStatus();
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
    const navTypeA = document.getElementById('nav-type-a');
    if (navTypeA) {
        navTypeA.addEventListener('click', (e) => switchTab('type-a', e));
    }
    const navTypeB = document.getElementById('nav-type-b');
    if (navTypeB) {
        navTypeB.addEventListener('click', (e) => switchTab('type-b', e));
    }
    const navTypeC = document.getElementById('nav-type-c');
    if (navTypeC) {
        navTypeC.addEventListener('click', (e) => switchTab('type-c', e));
    }
    const navExec = document.getElementById('nav-executions');
    if (navExec) {
        navExec.addEventListener('click', (e) => switchTab('executions', e));
    }
    const navTesting = document.getElementById('nav-testing');
    if (navTesting) {
        navTesting.addEventListener('click', (e) => switchTab('testing', e));
    }
    const navGuide = document.getElementById('nav-guide');
    if (navGuide) {
        navGuide.addEventListener('click', (e) => switchTab('guide', e));
    }

    // Poll every 1 second for live simulation status & queue progress
    setInterval(() => {
        fetchDashboardStats();
        fetchAutomations();
        fetchLanesStatus();
        checkSchedulerStatus();
        if (activeTab === 'executions') {
            fetchExecutionHistory();
        }
    }, 1000);

    // Poll timeline every 5 seconds to reduce polling overhead
    setInterval(() => {
        fetchTimeline();
    }, 5000);
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
    } else if (tabName === 'type-a') {
        const navTypeA = document.getElementById('nav-type-a');
        if (navTypeA) navTypeA.classList.add('active');
        const viewTypeA = document.getElementById('view-type-a');
        if (viewTypeA) {
            viewTypeA.style.display = 'grid';
            viewTypeA.classList.add('active');
        }
    } else if (tabName === 'type-b') {
        const navTypeB = document.getElementById('nav-type-b');
        if (navTypeB) navTypeB.classList.add('active');
        const viewTypeB = document.getElementById('view-type-b');
        if (viewTypeB) {
            viewTypeB.style.display = 'grid';
            viewTypeB.classList.add('active');
        }
    } else if (tabName === 'type-c') {
        const navTypeC = document.getElementById('nav-type-c');
        if (navTypeC) navTypeC.classList.add('active');
        const viewTypeC = document.getElementById('view-type-c');
        if (viewTypeC) {
            viewTypeC.style.display = 'grid';
            viewTypeC.classList.add('active');
        }
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
    } else if (tabName === 'testing') {
        const navTesting = document.getElementById('nav-testing');
        if (navTesting) navTesting.classList.add('active');
        const viewTesting = document.getElementById('view-testing');
        if (viewTesting) {
            viewTesting.style.display = 'block';
            viewTesting.classList.add('active');
        }
        fetchSettings();
        updateTestingBadge();
    } else if (tabName === 'settings') {
        const navSettings = document.getElementById('nav-settings');
        if (navSettings) navSettings.classList.add('active');
        const viewSettings = document.getElementById('view-settings');
        if (viewSettings) {
            viewSettings.style.display = 'grid';
            viewSettings.classList.add('active');
        }
        fetchSettings();
    } else if (tabName === 'guide') {
        const navGuide = document.getElementById('nav-guide');
        if (navGuide) navGuide.classList.add('active');
        const viewGuide = document.getElementById('view-guide');
        if (viewGuide) {
            viewGuide.style.display = 'block';
            viewGuide.classList.add('active');
        }
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

let currentBlueprintTab = 'python';

function switchBlueprintTab(lang) {
    currentBlueprintTab = lang;
    const pySnippet = document.getElementById('code-snippet-python');
    const rSnippet = document.getElementById('code-snippet-r');
    const tabBtns = document.querySelectorAll('.btn-code-tab');

    if (lang === 'python') {
        if (pySnippet) pySnippet.style.display = 'block';
        if (rSnippet) rSnippet.style.display = 'none';
        if (tabBtns[0]) tabBtns[0].classList.add('active');
        if (tabBtns[1]) tabBtns[1].classList.remove('active');
    } else {
        if (pySnippet) pySnippet.style.display = 'none';
        if (rSnippet) rSnippet.style.display = 'block';
        if (tabBtns[0]) tabBtns[0].classList.remove('active');
        if (tabBtns[1]) tabBtns[1].classList.add('active');
    }
}

function copyActiveBlueprint() {
    const snippetEl = currentBlueprintTab === 'python' 
        ? document.getElementById('code-snippet-python') 
        : document.getElementById('code-snippet-r');
    if (!snippetEl) return;

    const text = snippetEl.innerText || snippetEl.textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.querySelector('.btn-copy-code');
        if (btn) {
            const orig = btn.innerText;
            btn.innerText = '✓ Copied!';
            btn.style.color = '#34d399';
            setTimeout(() => {
                btn.innerText = orig;
                btn.style.color = '';
            }, 2000);
        }
    }).catch(err => {
        console.error('Failed to copy blueprint:', err);
    });
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

let isSchedulerRunning = false;
let transitionCooldownRemaining = 0;
let transitionCooldownTimer = null;

const lanesState = {
    type_a: { running: false, cooldown: 0, timer: null, active_runs: 0, max_concurrent_run: 1 },
    type_b: { running: false, cooldown: 0, timer: null, active_runs: 0 },
    type_c: { running: false, cooldown: 0, timer: null, active_runs: 0 }
};

function normalizeLaneKey(lane) {
    const l = String(lane || '').toLowerCase();
    if (l.includes('b')) return 'type_b';
    if (l.includes('c')) return 'type_c';
    return 'type_a';
}

function showToast(msg, type = 'info') {
    let container = document.getElementById('global-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'global-toast-container';
        container.style.cssText = 'position: fixed; bottom: 24px; right: 24px; z-index: 99999; display: flex; flex-direction: column; gap: 8px; max-width: 440px;';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    const isError = (type === 'error' || type === 'warn' || type === 'warning');
    toast.className = `settings-toast ${isError ? 'toast-error' : 'toast-success'}`;
    toast.style.cssText = 'box-shadow: 0 4px 20px rgba(0,0,0,0.5); backdrop-filter: blur(8px); cursor: pointer;';
    const icon = isError ? '⚠ ' : (type === 'success' ? '✓ ' : 'ℹ ');
    toast.innerText = icon + msg;
    toast.onclick = () => toast.remove();
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(6px)';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

async function startLane(lane) {
    const key = normalizeLaneKey(lane);
    try {
        const res = await fetch('/api/paradiso/lane/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lane: key })
        });
        const data = await res.json();
        if (data.cooldown_remaining && data.cooldown_remaining > 0) {
            startLaneCooldown(key, data.cooldown_remaining);
        }
        if (!data.ok && res.status === 429) {
            showToast(`Lane cooldown active: please wait ${Math.ceil(data.cooldown_remaining || 10)}s`, 'error');
            return;
        }
        if (!data.ok && res.status === 409) {
            showToast(data.error || `Lane start blocked outside the intraday open window.`, 'error');
            return;
        }
        if (!data.ok) {
            showToast(data.error || `Failed to start lane ${key}`, 'error');
            return;
        }
        await fetchLanesStatus();
        fetchDashboardStats();
    } catch (err) {
        console.error(`Failed to start lane ${key}:`, err);
        showToast(`Network error starting lane ${key}`, 'error');
    }
}

async function stopLane(lane) {
    const key = normalizeLaneKey(lane);
    try {
        const res = await fetch('/api/paradiso/lane/stop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lane: key })
        });
        const data = await res.json();
        if (data.cooldown_remaining && data.cooldown_remaining > 0) {
            startLaneCooldown(key, data.cooldown_remaining);
        }
        if (!data.ok && res.status === 429) {
            showToast(`Lane cooldown active: please wait ${Math.ceil(data.cooldown_remaining || 10)}s`, 'error');
            return;
        }
        if (!data.ok) {
            showToast(data.error || `Failed to stop lane ${key}`, 'error');
            return;
        }
        await fetchLanesStatus();
        fetchDashboardStats();
    } catch (err) {
        console.error(`Failed to stop lane ${key}:`, err);
        showToast(`Network error stopping lane ${key}`, 'error');
    }
}

function startLaneCooldown(laneKey, seconds) {
    const s = lanesState[laneKey];
    if (!s) return;
    s.cooldown = Math.max(1, Math.ceil(seconds || 10));
    updateLaneUI(laneKey);

    if (s.timer) clearInterval(s.timer);
    s.timer = setInterval(() => {
        s.cooldown -= 1;
        if (s.cooldown <= 0) {
            clearInterval(s.timer);
            s.timer = null;
            s.cooldown = 0;
            fetchLanesStatus();
        } else {
            updateLaneUI(laneKey);
        }
    }, 1000);
}

function updateLaneUI(laneKey) {
    const s = lanesState[laneKey];
    if (!s) return;

    const tabSuffix = laneKey === 'type_a' ? 'a' : (laneKey === 'type_b' ? 'b' : 'c');
    const isRunning = s.running;
    const inCooldown = s.cooldown > 0;

    // 1. Top bar elements
    const topStartBtn = document.getElementById(`btn-top-start-${laneKey}`);
    const topStopBtn = document.getElementById(`btn-top-stop-${laneKey}`);
    const topStatus = document.getElementById(`top-status-${laneKey}`);

    // 2. Dashboard hub elements
    const dashStartBtn = document.getElementById(`btn-dash-start-${laneKey}`);
    const dashStopBtn = document.getElementById(`btn-dash-stop-${laneKey}`);
    const dashStatus = document.getElementById(`dash-status-${laneKey}`);

    // 3. Tab view header elements
    const tabStartBtn = document.getElementById(`btn-start-lane-${tabSuffix}`);
    const tabStopBtn = document.getElementById(`btn-stop-lane-${tabSuffix}`);
    const tabBadge = document.getElementById(`lane-${tabSuffix}-badge`);

    const configureBtn = (startBtn, stopBtn, isTop) => {
        if (!startBtn || !stopBtn) return;
        if (inCooldown) {
            startBtn.disabled = true;
            stopBtn.disabled = true;
            startBtn.innerHTML = `⏳ ${s.cooldown}s`;
            startBtn.style.display = 'inline-flex';
            stopBtn.style.display = 'none';
        } else if (isRunning) {
            startBtn.style.display = 'none';
            stopBtn.disabled = false;
            stopBtn.innerHTML = isTop ? '⏹ Stop' : `⏹ Stop Lane ${tabSuffix.toUpperCase()}`;
            stopBtn.style.display = 'inline-flex';
        } else {
            startBtn.disabled = false;
            startBtn.innerHTML = isTop ? '▶ Start' : `▶ Start Lane ${tabSuffix.toUpperCase()}`;
            startBtn.style.display = 'inline-flex';
            stopBtn.style.display = 'none';
        }
    };

    const configureStatus = (badgeEl) => {
        if (!badgeEl) return;
        if (isRunning) {
            badgeEl.innerHTML = '● Active';
            badgeEl.style.color = '#34d399';
            if (badgeEl.classList.contains('badge')) {
                badgeEl.style.background = 'rgba(52, 211, 153, 0.15)';
                badgeEl.style.borderColor = 'rgba(52, 211, 153, 0.4)';
            }
        } else {
            badgeEl.innerHTML = '○ Standby';
            badgeEl.style.color = 'var(--text-muted)';
            if (badgeEl.classList.contains('badge')) {
                badgeEl.style.background = 'rgba(140, 150, 171, 0.15)';
                badgeEl.style.borderColor = 'rgba(140, 150, 171, 0.3)';
            }
        }
    };

    configureBtn(topStartBtn, topStopBtn, true);
    configureStatus(topStatus);

    configureBtn(dashStartBtn, dashStopBtn, false);
    configureStatus(dashStatus);

    configureBtn(tabStartBtn, tabStopBtn, false);
    configureStatus(tabBadge);

    // 4. Lane A specific Concurrency Pool metrics
    if (laneKey === 'type_a') {
        const maxSlots = s.max_concurrent_run || 1;
        const modeBadge = document.getElementById('lane-a-mode-badge');
        if (modeBadge) {
            modeBadge.innerText = maxSlots > 1 ? `Concurrent Pool (${maxSlots} Slots)` : 'Single-Threaded FIFO';
        }
        const modeNum = document.getElementById('metric-a-mode-num');
        if (modeNum) {
            modeNum.innerText = maxSlots > 1 ? `${maxSlots}-at-a-time` : '1-at-a-time';
        }
        const modeSub = document.getElementById('metric-a-mode-sub');
        if (modeSub) {
            modeSub.innerText = maxSlots > 1 ? `Parallel Slot Semaphore Pool` : 'Strict FIFO Queue (1 Slot)';
        }
        const activeSlots = document.getElementById('metric-a-active-slots');
        if (activeSlots) {
            if (isRunning) {
                activeSlots.innerText = `${s.active_runs} / ${maxSlots} Active`;
                activeSlots.style.color = s.active_runs > 0 ? '#34d399' : '#60a5fa';
            } else {
                activeSlots.innerText = `0 / ${maxSlots} Standby`;
                activeSlots.style.color = 'var(--text-muted)';
            }
        }
        const slotsSub = document.getElementById('metric-a-slots-sub');
        if (slotsSub) {
            slotsSub.innerText = `Max ${maxSlots} in-flight process${maxSlots > 1 ? 'es' : ''} permitted`;
        }
    }
}

async function fetchLanesStatus() {
    try {
        const res = await fetch('/api/paradiso/lanes/status');
        const data = await res.json();
        if (!data.ok || !data.lanes) return;

        ['type_a', 'type_b', 'type_c'].forEach(k => {
            const laneInfo = data.lanes[k];
            if (!laneInfo) return;
            lanesState[k].running = Boolean(laneInfo.running);
            lanesState[k].active_runs = laneInfo.running_count || 0;
            if (laneInfo.max_concurrent_run) {
                lanesState[k].max_concurrent_run = laneInfo.max_concurrent_run;
            }
            if (laneInfo.cooldown_remaining && laneInfo.cooldown_remaining > 0 && lanesState[k].cooldown <= 0) {
                startLaneCooldown(k, laneInfo.cooldown_remaining);
            }
            updateLaneUI(k);
        });

        // Update system status line in panel
        const sysScheduler = document.getElementById('sys-status-scheduler');
        if (sysScheduler) {
            const runningLanes = Object.entries(lanesState).filter(([_, s]) => s.running).map(([k, _]) => k.replace('type_', '').toUpperCase());
            if (runningLanes.length > 0) {
                sysScheduler.innerHTML = `✓ Scheduler: Active (Lanes: ${runningLanes.join(', ')})`;
                sysScheduler.style.color = '#34d399';
            } else {
                sysScheduler.innerHTML = '○ Scheduler: Standby';
                sysScheduler.style.color = 'var(--text-muted)';
            }
        }
    } catch (e) {
        console.error('Failed to fetch lanes status:', e);
    }
}

function updateSchedulerButtonUI() {
    // Kept for backward compatibility
}

function startTransitionCooldown(seconds) {
    transitionCooldownRemaining = Math.max(1, Math.ceil(seconds || 10));
    if (transitionCooldownTimer) clearInterval(transitionCooldownTimer);
    transitionCooldownTimer = setInterval(() => {
        transitionCooldownRemaining -= 1;
        if (transitionCooldownRemaining <= 0) {
            clearInterval(transitionCooldownTimer);
            transitionCooldownTimer = null;
            transitionCooldownRemaining = 0;
        }
    }, 1000);
}

async function checkSchedulerStatus() {
    try {
        const res = await fetch('/api/paradiso/status');
        const data = await res.json();
        if (data.ok) {
            isSchedulerRunning = Boolean(data.running);
            if (data.cooldown_remaining && data.cooldown_remaining > 0 && transitionCooldownRemaining <= 0) {
                startTransitionCooldown(data.cooldown_remaining);
            }
        }
        updateSettingsLockUI();
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
                <div style="display: flex; gap: 6px;">
                    ${item.status !== 'Disabled' ? `
                    <button type="button" class="btn-card-action" onclick="disableReport('${escapeHtml(item.name)}')" title="Disable report from scheduling">
                        ⏸ Disable
                    </button>` : ''}
                    <button type="button" class="btn-card-action" onclick="deleteReport('${escapeHtml(item.name)}')" title="Delete report from catalog">
                        🗑 Delete
                    </button>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}

function handleReportTypeChange(laneType) {
    const laneBadge = document.getElementById('lane-badge');
    const laneHint = document.getElementById('new-report-type-hint');
    const groupLaneB = document.getElementById('group-lane-b-config');
    const groupLaneC = document.getElementById('group-lane-c-config');

    if (laneBadge) {
        if (laneType === 'type_b') {
            laneBadge.innerText = 'Lane B';
            laneBadge.className = 'badge badge-running';
            laneBadge.style.background = 'rgba(96, 165, 250, 0.2)';
            laneBadge.style.color = '#60a5fa';
            laneBadge.style.borderColor = 'rgba(96, 165, 250, 0.4)';
        } else if (laneType === 'type_c') {
            laneBadge.innerText = 'Lane C';
            laneBadge.className = 'badge badge-completed';
            laneBadge.style.background = 'rgba(168, 85, 247, 0.2)';
            laneBadge.style.color = '#c084fc';
            laneBadge.style.borderColor = 'rgba(168, 85, 247, 0.4)';
        } else {
            laneBadge.innerText = 'Lane A';
            laneBadge.className = 'badge badge-waiting';
            laneBadge.style.background = 'rgba(234, 179, 8, 0.2)';
            laneBadge.style.color = '#facc15';
            laneBadge.style.borderColor = 'rgba(234, 179, 8, 0.4)';
        }
    }

    if (laneHint) {
        if (laneType === 'type_b') {
            laneHint.innerText = 'Autonomous interval cadence throughout intraday operating hours.';
        } else if (laneType === 'type_c') {
            laneHint.innerText = 'Fixed timeslot dispatch with configurable missed catch-up policies.';
        } else {
            laneHint.innerText = 'Executes via FIFO queue or concurrency pool during open operating hours.';
        }
    }

    if (groupLaneB) {
        groupLaneB.style.display = (laneType === 'type_b') ? 'block' : 'none';
    }
    if (groupLaneC) {
        groupLaneC.style.display = (laneType === 'type_c') ? 'flex' : 'none';
    }
}

function handleTimeslotTierChange(tier) {
    const timeInput = document.getElementById('new-report-time');
    if (!timeInput) return;
    if (tier === 'BOD') {
        timeInput.value = '07:00';
    } else if (tier === 'MID') {
        timeInput.value = '12:00';
    } else if (tier === 'EOD') {
        timeInput.value = '20:30';
    }
}

function handleFileTypeChange(filetype) {
    const dirInput = document.getElementById('new-report-dir');
    const filenameHint = document.getElementById('new-report-filename-hint');
    const isPy = (filetype || '').toLowerCase() === 'python';

    if (filenameHint) {
        filenameHint.innerText = isPy ? 'Executable script filename (.py)' : 'Executable script filename (.R or .r)';
    }

    if (dirInput) {
        if (!dirInput.value || dirInput.value === '../reports' || dirInput.value === '../reports/python' || dirInput.value === '../reports/r') {
            dirInput.value = isPy ? '../reports/python' : '../reports/r';
        }
    }
}

function handleAddModalKeydown(e) {
    if (e.key === 'Escape') {
        closeAddReportModal();
    }
}

function openAddReportModal(defaultLane = 'type_a') {
    const modal = document.getElementById('modal-add-report');
    if (!modal) return;
    const form = document.getElementById('form-add-report');
    if (form) form.reset();
    const err = document.getElementById('add-report-error');
    if (err) {
        err.style.display = 'none';
        err.innerText = '';
    }

    const typeSelect = document.getElementById('new-report-type');
    const resolvedLane = (defaultLane && ['type_a', 'type_b', 'type_c'].includes(defaultLane)) ? defaultLane : 'type_a';
    if (typeSelect) typeSelect.value = resolvedLane;

    const filetypeSelect = document.getElementById('new-report-filetype');
    if (filetypeSelect) filetypeSelect.value = 'python';

    const dirInput = document.getElementById('new-report-dir');
    if (dirInput) dirInput.value = '../reports/python';

    const teamInput = document.getElementById('new-report-team');
    if (teamInput) teamInput.value = 'General';

    const ownerInput = document.getElementById('new-report-owner');
    if (ownerInput) ownerInput.value = 'User';

    const timeInput = document.getElementById('new-report-time');
    if (timeInput) timeInput.value = '08:30';

    const intervalInput = document.getElementById('new-report-interval');
    if (intervalInput) intervalInput.value = '30';

    const tierSelect = document.getElementById('new-report-tier');
    if (tierSelect) tierSelect.value = 'CUSTOM';

    const catchUpSelect = document.getElementById('new-report-catch-up');
    if (catchUpSelect) catchUpSelect.value = '';

    const statusSelect = document.getElementById('new-report-status');
    if (statusSelect) statusSelect.value = 'Waiting';

    handleReportTypeChange(resolvedLane);
    handleFileTypeChange('python');

    modal.classList.add('active');

    setTimeout(() => {
        const nameInput = document.getElementById('new-report-name');
        if (nameInput) nameInput.focus();
    }, 50);

    window.addEventListener('keydown', handleAddModalKeydown);
}

function closeAddReportModal() {
    const modal = document.getElementById('modal-add-report');
    if (modal) modal.classList.remove('active');
    window.removeEventListener('keydown', handleAddModalKeydown);
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
    const origText = btn ? btn.innerText : '💾 Save & Register Report';

    const name = (document.getElementById('new-report-name')?.value || '').trim();
    const filename = (document.getElementById('new-report-filename')?.value || '').trim();
    const report_type = (document.getElementById('new-report-type')?.value || 'type_a');
    const filetype = (document.getElementById('new-report-filetype')?.value || 'python').toLowerCase();
    const dir = (document.getElementById('new-report-dir')?.value || (filetype === 'python' ? '../reports/python' : '../reports/r')).trim();
    const team = (document.getElementById('new-report-team')?.value || 'General').trim();
    const owner = (document.getElementById('new-report-owner')?.value || 'User').trim();
    const scheduled_time = (document.getElementById('new-report-time')?.value || '08:30').trim();
    const status = (document.getElementById('new-report-status')?.value || 'Waiting');

    const intervalVal = parseInt(document.getElementById('new-report-interval')?.value, 10);
    const interval_minutes = isNaN(intervalVal) ? 30 : intervalVal;
    const timeslot_tier = (document.getElementById('new-report-tier')?.value || 'CUSTOM');
    const catch_up_raw = (document.getElementById('new-report-catch-up')?.value || '').trim();
    const catch_up_policy = catch_up_raw ? catch_up_raw : null;

    if (!name || !filename) {
        if (errEl) {
            errEl.innerText = 'Report name and filename are required.';
            errEl.style.display = 'block';
        }
        return;
    }

    if (filename.includes('/') || filename.includes('\\') || filename.includes('..')) {
        if (errEl) {
            errEl.innerText = 'Filename must be a bare filename without path separators or traversal characters.';
            errEl.style.display = 'block';
        }
        return;
    }

    if (filetype === 'python' && !filename.endsWith('.py')) {
        if (errEl) {
            errEl.innerText = 'Python scripts must end with .py';
            errEl.style.display = 'block';
        }
        return;
    }

    if (filetype === 'r' && !filename.toLowerCase().endsWith('.r')) {
        if (errEl) {
            errEl.innerText = 'R scripts must end with .R or .r';
            errEl.style.display = 'block';
        }
        return;
    }

    const timeRegex = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (!timeRegex.test(scheduled_time)) {
        if (errEl) {
            errEl.innerText = `Invalid scheduled time "${scheduled_time}": must be 24-hr format HH:MM (e.g. 08:30, 14:15).`;
            errEl.style.display = 'block';
        }
        return;
    }

    if (report_type === 'type_b' && interval_minutes < 1) {
        if (errEl) {
            errEl.innerText = 'Lane B recurring interval must be an integer >= 1.';
            errEl.style.display = 'block';
        }
        return;
    }

    if (errEl) {
        errEl.style.display = 'none';
        errEl.innerText = '';
    }

    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Registering...';
    }

    try {
        const payload = {
            name,
            filename,
            filetype,
            dir,
            team,
            owner,
            scheduled_time,
            status,
            report_type,
            interval_minutes,
            timeslot_tier,
            catch_up_policy
        };

        const res = await fetch('/api/automation/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.ok) {
            closeAddReportModal();
            const laneLabel = report_type === 'type_b' ? 'Lane B' : (report_type === 'type_c' ? 'Lane C' : 'Lane A');
            showSettingsToast(data.message || `Report '${name}' registered successfully in ${laneLabel}!`, 'success');
            await fetchAutomations();
            await fetchDashboardStats();
            if (typeof fetchLanesStatus === 'function') {
                await fetchLanesStatus();
            }
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
        if (btn) {
            btn.disabled = false;
            btn.innerText = origText;
        }
    }
}

async function disableReport(name) {
    if (!confirm(`Are you sure you want to disable report '${name}'? This will remove it from today's active execution queue.`)) {
        return;
    }

    try {
        const res = await fetch('/api/automation/disable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await res.json();
        if (data.ok) {
            showToast(data.message || `Report '${name}' disabled.`, 'success');
            await fetchAutomations();
            await fetchDashboardStats();
        } else {
            showToast(data.error || 'Failed to disable report.', 'error');
        }
    } catch (e) {
        console.error('Disable report error:', e);
        showToast('Network error disabling report.', 'error');
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
        const res = await fetch('/api/dashboard/timeline?limit=50');
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
    if (transitionCooldownRemaining > 0) return;
    try {
        const res = await fetch('/api/paradiso/start', { method: 'POST' });
        const data = await res.json();
        if (res.status === 429) {
            startTransitionCooldown(data.cooldown_remaining || 10);
            return;
        }
        if (data.ok) {
            startTransitionCooldown(10);
        }
    } catch (e) {
        console.error('Failed to start scheduler:', e);
    }
    checkSchedulerStatus();
    fetchAutomations();
}

async function stopScheduler() {
    if (transitionCooldownRemaining > 0) return;
    try {
        const res = await fetch('/api/paradiso/stop', { method: 'POST' });
        const data = await res.json();
        if (res.status === 429) {
            startTransitionCooldown(data.cooldown_remaining || 10);
            return;
        }
        if (data.ok) {
            startTransitionCooldown(10);
        }
    } catch (e) {
        console.error('Failed to stop scheduler:', e);
    }
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

        const maxConcEl = document.getElementById('setting-max-concurrent');
        if (maxConcEl) maxConcEl.value = sched.max_concurrent_run || 1;

        // Simulation fields
        const simEnabledEl = document.getElementById('setting-sim-enabled');
        if (simEnabledEl) simEnabledEl.value = sim.enabled ? "true" : "false";

        const simSpeedEl = document.getElementById('setting-sim-speed');
        if (simSpeedEl) simSpeedEl.value = parseFloat(sim.speed_multiplier || 600.0).toFixed(1);

        toggleSimSpeedDisabled();
        updateTestingBadge();

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
        updateSettingsLockUI();
    } catch (e) {
        console.error('Failed to fetch settings:', e);
        showSettingsToast('Failed to load settings from server.', 'error');
    }
}

function updateSettingsLockUI() {
    const banner = document.getElementById('settings-locked-banner');
    const saveBtn = document.getElementById('btn-save-settings');
    if (!saveBtn) return;

    if (isSchedulerRunning) {
        if (banner) banner.style.display = 'block';
        saveBtn.disabled = true;
        saveBtn.title = 'Settings cannot be modified while Paradiso scheduler is running';
        saveBtn.style.opacity = '0.5';
        saveBtn.style.cursor = 'not-allowed';
    } else {
        if (banner) banner.style.display = 'none';
        saveBtn.disabled = false;
        saveBtn.title = '';
        saveBtn.style.opacity = '1';
        saveBtn.style.cursor = 'pointer';
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
    if (isSchedulerRunning) {
        showSettingsToast('Settings cannot be modified while Paradiso scheduler is running. Please stop Paradiso before updating settings.', 'error');
        return;
    }

    const timeRegex = /^([01]\d|2[0-3]):[0-5]\d$/;
    const startTime = document.getElementById('setting-start-time').value.trim();
    const idleTime = document.getElementById('setting-idle-time').value.trim();
    const closeTime = document.getElementById('setting-close-time').value.trim();

    if (!timeRegex.test(startTime) || !timeRegex.test(idleTime) || !timeRegex.test(closeTime)) {
        showSettingsToast('Scheduler times must be in 24-hour HH:MM format (e.g., 07:00).', 'error');
        return;
    }
    if (!(startTime < idleTime && idleTime <= closeTime)) {
        showSettingsToast('Scheduler times must satisfy: Start Time < Idle Time <= Close Time.', 'error');
        return;
    }

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
            job_interval_seconds: parseInt(document.getElementById('setting-job-interval').value, 10) || 15,
            max_concurrent_run: parseInt(document.getElementById('setting-max-concurrent').value, 10) || 1
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
        if (res.status === 409 || !data.ok) {
            showSettingsToast(data.error || 'Settings cannot be modified while Paradiso scheduler is running.', 'error');
            return;
        }
        if (data.ok) {
            showSettingsToast(data.message || 'Settings saved and applied successfully!', 'success');
            fetchDashboardStats();
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
            showTestingToast('Simulation clock reset to midnight.', 'success');
            fetchDashboardStats();
            fetchTimeline();
        }
    } catch (e) {
        console.error('Error resetting clock:', e);
        showSettingsToast('Failed to reset simulation clock.', 'error');
        showTestingToast('Failed to reset simulation clock.', 'error');
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

async function applySimulationSettings() {
    if (isSchedulerRunning) {
        showTestingToast('Simulation settings cannot be changed while scheduler is running. Stop the scheduler first.', 'error');
        return;
    }
    const simEnabled = document.getElementById('setting-sim-enabled').value === 'true';
    const simSpeed = parseFloat(document.getElementById('setting-sim-speed').value);
    const btn = document.getElementById('btn-apply-simulation');
    const origText = btn ? btn.innerText : '';
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Applying...';
    }

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                simulation: {
                    enabled: simEnabled,
                    speed_multiplier: simSpeed
                }
            })
        });
        const data = await res.json();
        if (data.ok) {
            showTestingToast('Simulation settings applied successfully.', 'success');
            fetchDashboardStats();
            updateTestingBadge();
        } else {
            showTestingToast(data.error || 'Failed to apply simulation settings.', 'error');
        }
    } catch (err) {
        console.error('Error applying simulation settings:', err);
        showTestingToast('Network error while applying simulation settings.', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = origText;
        }
    }
}

async function resetAutomationsFromLab() {
    const btn = document.getElementById('btn-reset-test');
    const origText = btn ? btn.innerText : '';
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Resetting...';
    }
    try {
        await resetAutomations();
        showTestingToast('Intraday automations and queue reset for testing.', 'success');
    } catch (e) {
        showTestingToast('Failed to reset automations.', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = origText;
        }
    }
}

function showTestingToast(msg, type = 'success') {
    const banner = document.getElementById('testing-alert-banner');
    if (!banner) return;
    banner.className = `settings-toast ${type === 'success' ? 'toast-success' : 'toast-error'}`;
    banner.innerText = (type === 'success' ? '✓ ' : '⚠ ') + msg;
    banner.style.display = 'flex';
    clearTimeout(window._testingToastTimeout);
    window._testingToastTimeout = setTimeout(() => {
        banner.style.display = 'none';
    }, 4000);
}

function updateTestingBadge() {
    const badge = document.getElementById('testing-mode-badge');
    const simEnabled = document.getElementById('setting-sim-enabled');
    const simSpeed = document.getElementById('setting-sim-speed');
    if (!badge) return;
    if (simEnabled && simEnabled.value === 'true') {
        const speedText = simSpeed && simSpeed.selectedIndex >= 0 ? simSpeed.options[simSpeed.selectedIndex].text.split(' ')[0] : '600x';
        badge.innerText = `⚡ Fast-Forward Simulation (${speedText})`;
        badge.style.background = 'rgba(96, 165, 250, 0.15)';
        badge.style.color = '#60a5fa';
        badge.style.borderColor = 'rgba(96, 165, 250, 0.3)';
    } else {
        badge.innerText = '● Real System Wall-Clock';
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.color = '#34d399';
        badge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
    }
}

