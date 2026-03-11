const API_URL = window.location.origin;
let currentProject = null;
let currentWindowId = null;
let smellChart = null;
let devCommitsChart = null;
let devBugsChart = null;
let devChurnChart = null;
let devRoleChart = null;
let devSentimentTimelineChart = null;
let mlSmellTypeChart = null;
let traditionalSmellTypeChart = null;
let vulnTypeChart = null;
let vulnSeverityChart = null;

const COMMUNITY_METRICS_REFERENCE = [
    {
        title: 'Section 1 - Developer Social Network Metrics',
        notes: [
            'These metrics are computed on DSN node sets and their intersections.',
            'V_global = developers in global DSN, V_comm = communication DSN, V_collab = collaboration DSN.',
            'If explicit communication traces are missing, V_comm is inferred with a commit-based proxy: developers active on the same day are linked.'
        ],
        items: [
            { metric: 'devs', definition: 'Number of developers in the global DSN.', formula: 'devs = |V_global|', compute: 'Build global DSN and count unique developers.' },
            { metric: 'ml.only.devs', definition: 'Developers only in communication network.', formula: 'ml.only.devs = |V_comm - V_collab|' },
            { metric: 'code.only.devs', definition: 'Developers only in collaboration network.', formula: 'code.only.devs = |V_collab - V_comm|' },
            { metric: 'ml.code.devs', definition: 'Developers present in both networks.', formula: 'ml.code.devs = |V_comm ∩ V_collab|' },
            { metric: 'perc.ml.only.devs', definition: 'Share of developers only in communication network.', formula: 'perc.ml.only.devs = ml.only.devs / devs' },
            { metric: 'perc.code.only.devs', definition: 'Share of developers only in collaboration network.', formula: 'perc.code.only.devs = code.only.devs / devs' },
            { metric: 'perc.ml.code.devs', definition: 'Share of developers present in both networks.', formula: 'perc.ml.code.devs = ml.code.devs / devs' },
            { metric: 'sponsored.devs', definition: 'Developers considered sponsored (mostly working-hour commits).', formula: 'sponsored if work_ratio(d) = commits_during_work_hours(d) / total_commits(d) >= 0.95', compute: 'Use commit timestamps, define work hours (example Mon-Fri 09:00-18:00), then classify per developer.' },
            { metric: 'ratio.sponsored', definition: 'Ratio of sponsored developers over collaboration DSN developers.', formula: 'ratio.sponsored = sponsored.devs / |V_collab|' }
        ]
    },
    {
        title: 'Section 2 - Socio-Technical Metrics',
        notes: [
            'Communication is derived primarily from GitHub pull requests and issues (authors, assignees, comments, reviews).',
            'When explicit communication data is unavailable, communication links are inferred from same-day co-activity in commits.',
            'This is a proxy signal: it captures operational overlap, not direct conversations.'
        ],
        items: [
            { metric: 'st.congruence', definition: 'How much required coordination overlaps with actual communication.', formula: 'st.congruence = |Needs ∩ ActualCommunication| / |Needs|', compute: 'Needs = pairs that should coordinate (for example coupled artifacts). ActualCommunication = real communication links if available, otherwise commit-based proxy links from same-day co-activity.' },
            { metric: 'communicability', definition: 'How easily information propagates in the developer network.', formula: 'communicability = average(1 / distance(i,j)) over reachable pairs' },
            { metric: 'num.tz', definition: 'Number of distinct time zones represented in the project.', formula: 'num.tz = count(distinct developer time zones)', compute: 'Possible sources: commit metadata, developer profile, email headers.' },
            { metric: 'ratio.smelly.devs', definition: 'Share of developers involved in at least one community smell.', formula: 'ratio.smelly.devs = |developers_involved_in_smells| / devs' }
        ]
    },
    {
        title: 'Section 3 - Core Community Members Metrics',
        notes: [
            'Core developers are identified before these metrics (common rule: top contributors covering around 80% of commits).'
        ],
        items: [
            { metric: 'core.global.devs', definition: 'Number of core developers in global DSN.' },
            { metric: 'core.mail.devs', definition: 'Number of core developers in communication network.' },
            { metric: 'core.code.devs', definition: 'Number of core developers in collaboration network.' },
            { metric: 'sponsored.core.devs', definition: 'Developers that are both core and sponsored.' },
            { metric: 'ratio.sponsored.core', definition: 'Ratio of sponsored core developers over core code developers.', formula: 'ratio.sponsored.core = sponsored.core.devs / core.code.devs' },
            { metric: 'global.truck', definition: 'Ratio of non-core developers in global DSN.', formula: 'global.truck = non_core_developers / total_developers' },
            { metric: 'mail.truck', definition: 'Ratio of non-core developers in communication network.', formula: 'mail.truck = non_core_developers / total_developers' },
            { metric: 'code.truck', definition: 'Ratio of non-core developers in collaboration network.', formula: 'code.truck = non_core_developers / total_developers' }
        ]
    },
    {
        title: 'Section 4 - Turnover Metrics',
        notes: [
            'Turnover compares two consecutive time windows t-1 and t.',
            'Developers present in t-1 and absent in t are considered leavers.'
        ],
        items: [
            { metric: 'global.turnover', definition: 'Turnover on global DSN developers.', formula: 'global.turnover(t) = |V_global(t-1) - V_global(t)| / |V_global(t-1)|' },
            { metric: 'code.turnover', definition: 'Turnover on collaboration DSN developers.', formula: 'code.turnover(t) = |V_collab(t-1) - V_collab(t)| / |V_collab(t-1)|' },
            { metric: 'core.global.turnover', definition: 'Turnover for core developers in global DSN.', formula: 'same turnover formula applied to core set only' },
            { metric: 'core.mail.turnover', definition: 'Turnover for core developers in communication network.', formula: 'same turnover formula applied to core set only' },
            { metric: 'core.code.turnover', definition: 'Turnover for core developers in collaboration network.', formula: 'same turnover formula applied to core set only' },
            { metric: 'ratio.smelly.quitters', definition: 'Share of previous-window smelly developers who left.', formula: 'ratio.smelly.quitters = |SmellyDevelopers(t-1) - V_global(t)| / |SmellyDevelopers(t-1)|' }
        ]
    },
    {
        title: 'Section 5 - Social Network Analysis Metrics',
        notes: [
            'N = number of nodes, E = number of edges.'
        ],
        items: [
            { metric: 'closeness.centr', definition: 'Closeness centrality.', formula: 'closeness(i) = (N-1) / sum_j dist(i,j)', compute: 'Network-level value is often the average across nodes.' },
            { metric: 'betweenness.centr', definition: 'Betweenness centrality.', formula: 'betweenness(i) = sum_{s,t} sigma_st(i) / sigma_st' },
            { metric: 'degree.centr', definition: 'Degree centrality and normalized degree.', formula: 'degree(i) = number of incident edges; degree_norm(i) = degree(i)/(N-1)' },
            { metric: 'global.mod', definition: 'Modularity on global DSN.', formula: 'Q = (1/2m) * sum_ij [Aij - (k_i*k_j/2m)] * delta(c_i,c_j)' },
            { metric: 'mail.mod', definition: 'Modularity on communication DSN.', formula: 'same Newman-Girvan modularity Q' },
            { metric: 'code.mod', definition: 'Modularity on collaboration DSN.', formula: 'same Newman-Girvan modularity Q' },
            { metric: 'density', definition: 'Network density (undirected graph).', formula: 'density = 2|E| / (N*(N-1))' }
        ]
    }
];

// DOM Elements
const projectGrid = document.getElementById('projectGrid');
const addProjectBtn = document.getElementById('addProjectBtn');
const addProjectModal = document.getElementById('addProjectModal');
const addProjectForm = document.getElementById('addProjectForm');
const backBtn = document.getElementById('backBtn');
const exportCsvBtn = document.getElementById('exportCsvBtn');
const exportCsvAllBtn = document.getElementById('exportCsvAllBtn');
const projectListSection = document.getElementById('projectListSection');
const projectDetailSection = document.getElementById('projectDetailSection');
const reanalyzeBtn = document.getElementById('reanalyzeBtn');
const timeWindowSelect = document.getElementById('timeWindowSelect');
const timeWindowLabel = document.getElementById('timeWindowLabel');
const prevWindowBtn = document.getElementById('prevWindowBtn');
const nextWindowBtn = document.getElementById('nextWindowBtn');

// Init
document.addEventListener('DOMContentLoaded', () => {
    renderCommunityMetricsReference();
    fetchProjects();
});

addProjectBtn.onclick = () => {
    document.getElementById('projName').value = '';
    document.getElementById('projUrls').value = '';
    document.getElementById('projPath').value = '';
    document.getElementById('advancedOptions').style.display = 'none';
    document.getElementById('toggleAdvanced').innerText = 'Show Advanced Options';
    addProjectModal.classList.remove('hidden');
};

document.getElementById('closeModal').onclick = () => addProjectModal.classList.add('hidden');

document.getElementById('toggleAdvanced').onclick = (e) => {
    e.preventDefault();
    const adv = document.getElementById('advancedOptions');
    if (adv.style.display === 'none') {
        adv.style.display = 'block';
        e.target.innerText = 'Hide Advanced Options';
    } else {
        adv.style.display = 'none';
        e.target.innerText = 'Show Advanced Options';
    }
};

addProjectForm.onsubmit = async (e) => {
    e.preventDefault();
    const name = document.getElementById('projName').value.trim();
    const urlsRaw = document.getElementById('projUrls').value;
    const path = document.getElementById('projPath').value.trim();
    const urls = urlsRaw
        .split(/\r?\n|,/)
        .map(x => x.trim())
        .filter(Boolean);

    if (!urls.length) {
        alert('Please provide at least one repository URL.');
        return;
    }

    if (urls.length > 1 && path) {
        alert('Local path can be used only when adding a single repository.');
        return;
    }

    if (urls.length === 1) {
        const url = urls[0];
        const inferredName = url.replace(/\/+$/, '').split('/').pop()?.replace(/\.git$/, '') || 'repository';
        const projectName = name || inferredName;
        const res = await fetch(
            `${API_URL}/projects?name=${encodeURIComponent(projectName)}&url=${encodeURIComponent(url)}&local_path=${encodeURIComponent(path)}`,
            { method: 'POST' }
        );
        const body = await res.json();
        if (!res.ok) {
            alert(body?.detail || 'Failed to add project.');
            return;
        }

        await fetch(`${API_URL}/projects/${body.id}/analyze`, { method: 'POST' });
        addProjectModal.classList.add('hidden');
        fetchProjects();
        return;
    }

    const repositories = urls.map((url, idx) => {
        const inferred = url.replace(/\/+$/, '').split('/').pop()?.replace(/\.git$/, '') || `repository-${idx + 1}`;
        const itemName = name ? `${name} ${idx + 1}` : inferred;
        return { url, name: itemName };
    });

    const res = await fetch(`${API_URL}/projects/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repositories, auto_analyze: true }),
    });
    const body = await res.json();
    if (!res.ok) {
        alert(body?.detail || 'Failed to add repositories.');
        return;
    }

    const createdCount = Array.isArray(body.created) ? body.created.length : 0;
    const errorCount = Array.isArray(body.errors) ? body.errors.length : 0;
    if (errorCount) {
        const sample = body.errors.slice(0, 3).map(ei => `${ei.url || `#${ei.index}`}: ${ei.error}`).join('\n');
        alert(`Created ${createdCount} repositories, ${errorCount} failed.\n${sample}`);
    }

    if (createdCount) {
        addProjectModal.classList.add('hidden');
        fetchProjects();
    }
};

backBtn.onclick = () => {
    projectDetailSection.classList.add('hidden');
    projectListSection.classList.remove('hidden');
};

exportCsvBtn.onclick = () => {
    if (!currentProject) return;
    let url = `${API_URL}/projects/${currentProject.id}/developers/export.csv`;
    if (currentWindowId) {
        url += `?window_id=${encodeURIComponent(currentWindowId)}`;
    }
    window.open(url, '_blank');
};

exportCsvAllBtn.onclick = () => {
    if (!currentProject) return;
    const url = `${API_URL}/projects/${currentProject.id}/developers/export.csv?all_windows=true`;
    window.open(url, '_blank');
};

prevWindowBtn.onclick = () => navigateWindow(-1);
nextWindowBtn.onclick = () => navigateWindow(1);

reanalyzeBtn.onclick = async () => {
    if (!currentProject) return;
    const res = await fetch(`${API_URL}/projects/${currentProject.id}/analyze`, { method: 'POST' });
    if (!res.ok) {
        alert('Failed to start analysis.');
        return;
    }
    document.getElementById('analysisStatus').innerText = 'Running';
    fetchProjects();
};

timeWindowSelect.onchange = (e) => {
    currentWindowId = e.target.value || null;
    renderSelectedWindow();
};

// Polling
let pollInterval = null;

async function fetchProjects() {
    try {
        const res = await fetch(`${API_URL}/projects`);
        const projects = await res.json();
        renderProjectGrid(projects);

        const anyRunning = projects.some(p => p.analysis_status === 'Running');
        if (anyRunning && !pollInterval) {
            pollInterval = setInterval(fetchProjects, 5000);
        } else if (!anyRunning && pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }

        if (currentProject) {
            const updated = projects.find(p => p.id === currentProject.id);
            if (updated && updated.analysis_status !== currentProject.analysis_status) {
                showDetail(updated.id);
            }
        }
    } catch (e) {
        console.error('Failed to fetch projects', e);
    }
}

function renderProjectGrid(projects) {
    projectGrid.innerHTML = '';
    projects.forEach(p => {
        const card = document.createElement('div');
        card.className = 'glass-card project-card';
        card.innerHTML = `
            <h3>${p.name}</h3>
            <p>${p.url}</p>
            <div class="status-badge">${p.analysis_status}</div>
            <button class="btn-primary" onclick="showDetail('${p.id}')" style="margin-top: 1rem; width: 100%">View Report</button>
            <button class="btn-secondary" onclick="deleteProject('${p.id}')" style="margin-top: 0.5rem; width: 100%; border-color: rgba(239, 68, 68, 0.5); color: #ef4444;">Delete Project</button>
        `;
        projectGrid.appendChild(card);
    });
}

function getProjectWindows(project) {
    if (!project) return [];
    const windows = Array.isArray(project.time_windows) ? project.time_windows : [];
    if (windows.length) return windows;
    if (project.analysis_status && project.analysis_status !== 'Completed') return [];

    const fallbackMetrics = (project.metrics && project.metrics.length > 0) ? project.metrics[0] : {
        loc: 0,
        nom: 0,
        community_smells_count: {},
        ml_smells_count: {},
        traditional_smells_count: {},
        vulnerabilities_count: {},
        vulnerabilities_severity_count: {}
    };

    return [{
        id: 'latest',
        label: 'Current Snapshot',
        start_date: null,
        end_date: null,
        developers: project.developers || [],
        metrics: fallbackMetrics,
        collaboration_edges: project.collaboration_edges || []
    }];
}

function getSelectedWindow(project) {
    const windows = getProjectWindows(project);
    if (!windows.length) return null;

    if (currentWindowId) {
        const byId = windows.find(w => w.id === currentWindowId);
        if (byId) return byId;
    }

    if (project && project.active_time_window_id) {
        const active = windows.find(w => w.id === project.active_time_window_id);
        if (active) {
            currentWindowId = active.id;
            return active;
        }
    }

    currentWindowId = windows[windows.length - 1].id;
    return windows[windows.length - 1];
}

function floorToUtcMonth(date) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
}

function parseWindowStartFromId(windowId) {
    if (typeof windowId !== 'string') return null;
    const match = /^(\d{4})(\d{2})(\d{2})_/.exec(windowId);
    if (!match) return null;
    const year = Number(match[1]);
    const monthIdx = Number(match[2]) - 1;
    const day = Number(match[3]);
    if (!Number.isFinite(year) || !Number.isFinite(monthIdx) || !Number.isFinite(day)) return null;
    return new Date(Date.UTC(year, monthIdx, day));
}

function getWindowStartDate(windowItem) {
    if (!windowItem) return null;

    const fromId = parseWindowStartFromId(windowItem.id);
    if (fromId) return floorToUtcMonth(fromId);

    if (!windowItem.start_date) return null;
    const dt = new Date(windowItem.start_date);
    if (Number.isNaN(dt.getTime())) return null;
    return floorToUtcMonth(dt);
}

function addUtcMonths(date, months) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + months, 1));
}

function navigateWindow(monthDelta) {
    const windows = getProjectWindows(currentProject);
    if (windows.length <= 1) return;

    let currentIdx = timeWindowSelect.selectedIndex;
    if (currentIdx < 0 || currentIdx >= windows.length) {
        currentIdx = windows.findIndex(w => w.id === currentWindowId);
    }
    if (currentIdx < 0) currentIdx = windows.length - 1;

    const candidate = currentIdx + monthDelta;
    if (candidate < 0 || candidate >= windows.length) return;

    currentWindowId = windows[candidate].id;
    timeWindowSelect.value = currentWindowId;
    renderSelectedWindow();
}

function renderTimeWindowSelector(project) {
    const windows = getProjectWindows(project);
    const selected = getSelectedWindow(project);

    if (!windows.length) {
        timeWindowSelect.innerHTML = '<option value="">No 3-month windows yet</option>';
        timeWindowSelect.value = '';
        prevWindowBtn.disabled = true;
        nextWindowBtn.disabled = true;
        return;
    }

    timeWindowSelect.innerHTML = windows
        .map(w => `<option value="${w.id}">${w.label}</option>`)
        .join('');

    if (selected) {
        timeWindowSelect.value = selected.id;
    }

    const idx = selected ? windows.findIndex(w => w.id === selected.id) : -1;
    prevWindowBtn.disabled = idx <= 0;
    nextWindowBtn.disabled = idx < 0 || idx >= windows.length - 1;
}

async function showDetail(projectId) {
    const res = await fetch(`${API_URL}/projects/${projectId}`);
    const project = await res.json();
    currentProject = project;

    projectListSection.classList.add('hidden');
    projectDetailSection.classList.remove('hidden');

    document.getElementById('detailProjectName').innerText = project.name;
    document.getElementById('analysisStatus').innerText = project.analysis_status;
    const mlStatus = project.ml_detection_error
        ? `${project.ml_detection_status || 'Unknown'} (${project.ml_detection_error})`
        : (project.ml_detection_status || 'Unknown');
    document.getElementById('mlDetectionStatus').innerText = mlStatus;

    renderTimeWindowSelector(project);
    renderSelectedWindow();
}

function renderSelectedWindow() {
    if (!currentProject) return;
    const selectedWindow = getSelectedWindow(currentProject);
    if (!selectedWindow) {
        renderTimeWindowSelector(currentProject);
        const status = currentProject.analysis_status || 'Unknown';
        timeWindowLabel.innerText = `No 3-month windows available (${status})`;
        document.getElementById('metricLoc').innerText = 0;
        document.getElementById('metricNom').innerText = 0;
        renderSmellChart({});
        renderCommunitySmellStatus({}, []);
        renderDeveloperList([]);
        renderNetwork([], []);
        renderDeveloperAnalytics([], {});
        renderCommunityMetricsReference({});
        return;
    }

    renderTimeWindowSelector(currentProject);
    timeWindowLabel.innerText = selectedWindow.label || 'Current Snapshot';

    const m = selectedWindow.metrics || {};
    document.getElementById('metricLoc').innerText = m.loc || 0;
    document.getElementById('metricNom').innerText = m.nom || 0;

    const windows = getProjectWindows(currentProject);
    const currentIdx = windows.findIndex(w => w.id === selectedWindow.id);
    const previousWindow = currentIdx > 0 ? windows[currentIdx - 1] : null;

    renderSmellChart(m);
    renderCommunitySmellStatus(m, selectedWindow.developers || []);
    renderDeveloperList(selectedWindow.developers || [], previousWindow ? (previousWindow.developers || []) : []);
    renderNetwork(selectedWindow.developers || [], selectedWindow.collaboration_edges || []);
    renderDeveloperAnalytics(selectedWindow.developers || [], m);
    renderCommunityMetricsReference(m.table3_metrics || {});
}

function renderSmellChart(metrics) {
    const ctx = document.getElementById('smellChart').getContext('2d');
    if (smellChart) smellChart.destroy();

    const labels = Object.keys(metrics.community_smells_count || {});
    const data = Object.values(metrics.community_smells_count || {});

    smellChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels.length ? labels : ['no_data'],
            datasets: [{
                data: data.length ? data : [0],
                backgroundColor: ['#6366f1', '#ec4899', '#10b981', '#f59e0b']
            }]
        },
        options: {
            plugins: { legend: { position: 'bottom', labels: { color: '#fff' } } }
        }
    });
}

function renderCommunitySmellStatus(metrics, developers) {
    const container = document.getElementById('communitySmellStatus');
    if (!container) return;

    const counts = metrics.community_smells_count || {};
    const instances = metrics.community_smell_instances || [];
    const total = Object.values(counts).reduce((s, n) => s + (Number(n) || 0), 0);
    const typeList = Object.entries(counts)
        .sort((a, b) => (b[1] || 0) - (a[1] || 0))
        .map(([k, v]) => `${formatSmellLabel(k)}: ${v}`)
        .join(', ');

    const involvedDevelopers = (developers || []).filter((d) => (d.community_smells || []).length > 0).length;

    if (total <= 0) {
        container.innerHTML = '<b>Community smells detected:</b> 0<br>No community smell was detected in this time window.';
        return;
    }

    const siloEvidences = instances
        .filter((x) => String(x.smell_id || '') === 'organisational_silo')
        .slice(0, 8)
        .map((x) => {
            const ev = x.evidence || {};
            const pair = Array.isArray(ev.pair) ? ev.pair.join(' <-> ') : '';
            const componentNodes = Array.isArray(ev.component_nodes) ? ev.component_nodes.join(', ') : '';
            const files = Array.isArray(ev.shared_files_sample) ? ev.shared_files_sample.join(', ') : '';
            const source = ev.communication_source ? String(ev.communication_source) : 'unknown';
            const weight = ev.collaboration_weight !== undefined ? `weight=${ev.collaboration_weight}` : '';
            const filesPart = ev.shared_files_count !== undefined ? `shared_files=${ev.shared_files_count}` : '';
            const details = [weight, filesPart].filter(Boolean).join(', ');
            if (pair) {
                return `<li><b>${escapeHtml(pair)}</b> (${escapeHtml(source)})${details ? ` - ${escapeHtml(details)}` : ''}${files ? `<br><span class="smell-evidence-files">${escapeHtml(files)}</span>` : ''}</li>`;
            }
            if (componentNodes) {
                return `<li><b>Isolated group</b> (${escapeHtml(source)}): ${escapeHtml(componentNodes)}</li>`;
            }
            return '';
        })
        .filter(Boolean)
        .join('');

    container.innerHTML = `
        <b>Community smells detected:</b> ${total}<br>
        <b>Developers involved:</b> ${involvedDevelopers}<br>
        <b>Types:</b> ${escapeHtml(typeList || 'n/a')}
        ${siloEvidences ? `<div class="smell-evidence"><b>Organizational Silo Evidence:</b><ul>${siloEvidences}</ul></div>` : ''}
    `;
}

async function deleteProject(projectId) {
    if (!confirm('Are you sure you want to delete this project? This will remove its local repository.')) return;

    try {
        await fetch(`${API_URL}/projects/${projectId}`, { method: 'DELETE' });
        fetchProjects();
    } catch (e) {
        console.error('Failed to delete project', e);
        alert('Failed to delete project');
    }
}

function buildCountMap(items, keyName) {
    const counts = {};
    (items || []).forEach((item) => {
        const key = item && item[keyName] ? String(item[keyName]) : null;
        if (!key) return;
        counts[key] = (counts[key] || 0) + 1;
    });
    return counts;
}

function formatCountBadges(counts, cssClass) {
    return Object.entries(counts || {})
        .sort((a, b) => b[1] - a[1])
        .map(([k, n]) => `<span class="badge ${cssClass}">${k.replace(/_/g, ' ')} x${n}</span>`)
        .join('');
}

function computeDelta(currCounts, prevCounts) {
    const keys = new Set([...Object.keys(currCounts || {}), ...Object.keys(prevCounts || {})]);
    let added = 0;
    let removed = 0;
    keys.forEach((k) => {
        const diff = (currCounts[k] || 0) - (prevCounts[k] || 0);
        if (diff > 0) added += diff;
        if (diff < 0) removed += Math.abs(diff);
    });
    return { added, removed };
}

function renderDeveloperList(developers, previousDevelopers = []) {
    const list = document.getElementById('developerList');
    list.innerHTML = '';
    const previousById = new Map((previousDevelopers || []).map((d) => [d.id, d]));
    developers.forEach((d) => {
        const item = document.createElement('div');
        item.className = 'dev-item';

        const prev = previousById.get(d.id) || {};
        const mlCounts = buildCountMap(d.ml_smell_details, 'smell_id');
        const mlPrevCounts = buildCountMap(prev.ml_smell_details, 'smell_id');
        const traditionalCounts = buildCountMap(d.traditional_smell_details, 'smell_id');
        const traditionalPrevCounts = buildCountMap(prev.traditional_smell_details, 'smell_id');
        const vulnCounts = buildCountMap(d.vulnerability_details, 'vuln_id');
        const vulnPrevCounts = buildCountMap(prev.vulnerability_details, 'vuln_id');

        if (!Object.keys(mlCounts).length) {
            (d.ml_smells || []).forEach((s) => { mlCounts[s] = (mlCounts[s] || 0) + 1; });
        }
        if (!Object.keys(mlPrevCounts).length) {
            (prev.ml_smells || []).forEach((s) => { mlPrevCounts[s] = (mlPrevCounts[s] || 0) + 1; });
        }
        if (!Object.keys(traditionalCounts).length) {
            (d.traditional_smells || []).forEach((s) => { traditionalCounts[s] = (traditionalCounts[s] || 0) + 1; });
        }
        if (!Object.keys(traditionalPrevCounts).length) {
            (prev.traditional_smells || []).forEach((s) => { traditionalPrevCounts[s] = (traditionalPrevCounts[s] || 0) + 1; });
        }
        if (!Object.keys(vulnCounts).length) {
            (d.vulnerabilities || []).forEach((s) => { vulnCounts[s] = (vulnCounts[s] || 0) + 1; });
        }
        if (!Object.keys(vulnPrevCounts).length) {
            (prev.vulnerabilities || []).forEach((s) => { vulnPrevCounts[s] = (vulnPrevCounts[s] || 0) + 1; });
        }

        const commBadges = (d.community_smells || [])
            .map(s => `<span class="badge badge-smell">${s.replace(/_/g, ' ')}</span>`)
            .join('');
        const mlBadges = formatCountBadges(mlCounts, 'badge-ml-smell');
        const traditionalBadges = formatCountBadges(traditionalCounts, 'badge-smell');
        const vulnBadges = formatCountBadges(vulnCounts, 'badge-vuln');

        const mlDelta = computeDelta(mlCounts, mlPrevCounts);
        const traditionalDelta = computeDelta(traditionalCounts, traditionalPrevCounts);
        const vulnDelta = computeDelta(vulnCounts, vulnPrevCounts);
        const deltaLine = `
            <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 6px;">
                vs prev: ML +${mlDelta.added}/-${mlDelta.removed},
                Traditional +${traditionalDelta.added}/-${traditionalDelta.removed},
                Vuln +${vulnDelta.added}/-${vulnDelta.removed}
            </div>
        `;

        let mlDetailsHtml = '';
        if (d.ml_smell_details && d.ml_smell_details.length > 0) {
            mlDetailsHtml = '<ul style="font-size: 0.8rem; margin-top: 5px; color: #a1a1aa; padding-left: 15px;">';
            d.ml_smell_details.forEach(detail => {
                const lineInfo = detail.line ? `(Line ${detail.line})` : '';
                mlDetailsHtml += `<li><b>${detail.smell_id.replace(/_/g, ' ')}</b> in <code>${detail.file}</code> ${lineInfo}</li>`;
            });
            mlDetailsHtml += '</ul>';
        }
        let traditionalDetailsHtml = '';
        if (d.traditional_smell_details && d.traditional_smell_details.length > 0) {
            traditionalDetailsHtml = '<ul style="font-size: 0.8rem; margin-top: 5px; color: #a1a1aa; padding-left: 15px;">';
            d.traditional_smell_details.forEach(detail => {
                const lineInfo = detail.line ? `(Line ${detail.line})` : '';
                traditionalDetailsHtml += `<li><b>${detail.smell_id.replace(/_/g, ' ')}</b> in <code>${detail.file}</code> ${lineInfo}</li>`;
            });
            traditionalDetailsHtml += '</ul>';
        }
        let vulnDetailsHtml = '';
        if (d.vulnerability_details && d.vulnerability_details.length > 0) {
            vulnDetailsHtml = '<ul style="font-size: 0.8rem; margin-top: 5px; color: #fda4af; padding-left: 15px;">';
            d.vulnerability_details.forEach(detail => {
                const lineInfo = detail.line ? `(Line ${detail.line})` : '';
                const sev = detail.severity ? `[${detail.severity}] ` : '';
                vulnDetailsHtml += `<li>${sev}<b>${formatSmellLabel(detail.vuln_id || detail.name)}</b> in <code>${detail.file}</code> ${lineInfo}</li>`;
            });
            vulnDetailsHtml += '</ul>';
        }

        item.innerHTML = `
            <div>
                <div>${d.id}</div>
                <div class="role">${d.classification} | Gender: ${d.gender || 'Unknown'}</div>
                <div class="smell-badges">${commBadges}${mlBadges}${traditionalBadges}${vulnBadges}</div>
                ${deltaLine}
                <div style="font-size: 0.78rem; color: #67e8f9; margin-top: 6px;">
                    Sentiment: <b>${d.sentiment_label || 'Unknown'}</b> (${Number(d.sentiment_score || 0).toFixed(3)}) from ${d.sentiment_messages_count || 0} messages
                </div>
                ${mlDetailsHtml}
                ${traditionalDetailsHtml}
                ${vulnDetailsHtml}
            </div>
            <div style="text-align: right; min-width: 80px;">
                <div class="accent-text">SE: ${d.se_score}</div>
                <div style="color: #ec4899">AI: ${d.ai_score}</div>
                <div style="color: #a78bfa">Gender conf: ${Number(d.gender_confidence || 0).toFixed(2)}</div>
                <div style="color: #f59e0b">Bugs: ${d.bug_introduced_count || 0}</div>
                <div style="color: #22c55e">Commits: ${d.commits_count || 0}</div>
                <div style="color: #38bdf8">Fixes: ${d.bug_fix_commits_count || 0}</div>
                <div style="color: #f97316">Churn: ${d.code_churn || 0}</div>
            </div>
        `;
        list.appendChild(item);
    });
}

function renderNetwork(developers, edgesData) {
    const edgeLengthFromWeight = (weight) => {
        const safeWeight = Math.max(1, Number(weight) || 1);
        const rawLength = 280 / Math.sqrt(safeWeight);
        return Math.max(80, Math.min(420, rawLength));
    };

    const nodes = (developers || []).map((dev, idx) => ({
        id: idx,
        label: (dev.aliases && dev.aliases[0]) || (dev.id || '').split('@')[0],
        color: dev.classification === 'AI-Engineer' ? '#ec4899' :
            dev.classification === 'Hybrid' ? '#f59e0b' : '#6366f1',
        title: `ID: ${dev.id}\nRole: ${dev.classification}\nGender: ${dev.gender || 'Unknown'} (${Number(dev.gender_confidence || 0).toFixed(2)})\nSE: ${dev.se_score} | AI: ${dev.ai_score}\n` +
            `Sentiment: ${dev.sentiment_label || 'Unknown'} (${Number(dev.sentiment_score || 0).toFixed(3)})\n` +
            `Commits: ${dev.commits_count || 0} | Fixes: ${dev.bug_fix_commits_count || 0}\n` +
            `Files touched: ${dev.files_touched_count || 0} | Churn: ${dev.code_churn || 0}\n` +
            `Bug-inducing commits (R-SZZ): ${dev.bug_introduced_count || 0}\n` +
            ((dev.community_smells || []).length ? `Community smells: ${(dev.community_smells || []).join(', ')}\n` : '') +
            ((dev.ml_smells || []).length ? `ML smells: ${(dev.ml_smells || []).join(', ')}\n` : '') +
            ((dev.traditional_smells || []).length ? `Traditional smells: ${(dev.traditional_smells || []).join(', ')}\n` : '') +
            ((dev.vulnerabilities || []).length ? `Vulnerabilities: ${(dev.vulnerabilities || []).join(', ')}` : '')
    }));

    const edges = (edgesData || []).map((e, i) => {
        const weight = Math.max(1, Number(e.weight) || 1);
        const targetLength = edgeLengthFromWeight(weight);
        return {
            id: i,
            from: e.from,
            to: e.to,
            length: targetLength,
            width: Math.min(8, 1 + Math.log2(weight + 1)),
            title: `Collaboration weight: ${weight}\nTarget distance: ${Math.round(targetLength)} (higher weight = shorter distance)`
        };
    });

    const container = document.getElementById('networkGraph');
    const data = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(edges)
    };
    const options = {
        nodes: { font: { color: '#fff', size: 12 }, size: 20, borderWidth: 2 },
        edges: {
            color: { color: 'rgba(100, 116, 139, 0.3)', highlight: 'rgba(99, 102, 241, 0.8)' },
            smooth: true
        },
        physics: {
            enabled: true,
            barnesHut: {
                gravitationalConstant: -4000,
                springLength: 250,
                springConstant: 0.03
            }
        },
        interaction: { tooltipDelay: 100 }
    };
    new vis.Network(container, data, options);
}

function renderDeveloperAnalytics(developers, metrics = {}) {
    const safeDevs = [...developers];
    safeDevs.sort((a, b) => (b.commits_count || 0) - (a.commits_count || 0));
    const top = safeDevs.slice(0, 12);

    const labels = top.map(d => (d.aliases && d.aliases[0]) || (d.id || 'dev').split('@')[0]);
    const commits = top.map(d => d.commits_count || 0);
    const bugIntro = top.map(d => d.bug_introduced_count || 0);
    const bugFix = top.map(d => d.bug_fix_commits_count || 0);
    const linesAdded = top.map(d => d.lines_added || 0);
    const linesDeleted = top.map(d => d.lines_deleted || 0);

    const totalDevs = developers.length;
    const totalCommits = developers.reduce((s, d) => s + (d.commits_count || 0), 0);
    const totalFixes = developers.reduce((s, d) => s + (d.bug_fix_commits_count || 0), 0);
    const totalBugIntro = developers.reduce((s, d) => s + (d.bug_introduced_count || 0), 0);
    const mlSmellCounts = metrics.ml_smells_count || {};
    const traditionalSmellCounts = metrics.traditional_smells_count || {};
    const vulnerabilityCounts = metrics.vulnerabilities_count || {};
    const vulnerabilitySeverityCounts = metrics.vulnerabilities_severity_count || {};
    const totalMlSmells = Object.values(mlSmellCounts).reduce((s, n) => s + (n || 0), 0);
    const totalTraditionalSmells = Object.values(traditionalSmellCounts).reduce((s, n) => s + (n || 0), 0);
    const totalVulnerabilities = Object.values(vulnerabilityCounts).reduce((s, n) => s + (n || 0), 0);
    const totalHighVulnerabilities = vulnerabilitySeverityCounts.HIGH || 0;
    const avgSentiment = developers.length
        ? developers.reduce((s, d) => s + (Number(d.sentiment_score) || 0), 0) / developers.length
        : 0;

    document.getElementById('devSummaryCount').innerText = totalDevs;
    document.getElementById('devSummaryCommits').innerText = totalCommits;
    document.getElementById('devSummaryFixes').innerText = totalFixes;
    document.getElementById('devSummaryBugs').innerText = totalBugIntro;
    document.getElementById('devSummaryMlSmells').innerText = totalMlSmells;
    document.getElementById('devSummaryTraditionalSmells').innerText = totalTraditionalSmells;
    document.getElementById('devSummaryVulnInstances').innerText = totalVulnerabilities;
    document.getElementById('devSummaryVulnHigh').innerText = totalHighVulnerabilities;
    document.getElementById('devSummarySentiment').innerText = avgSentiment.toFixed(3);

    const roleCounts = {};
    developers.forEach(d => {
        const role = d.classification || 'Unknown';
        roleCounts[role] = (roleCounts[role] || 0) + 1;
    });

    if (devCommitsChart) devCommitsChart.destroy();
    if (devBugsChart) devBugsChart.destroy();
    if (devChurnChart) devChurnChart.destroy();
    if (devRoleChart) devRoleChart.destroy();
    if (devSentimentTimelineChart) devSentimentTimelineChart.destroy();
    if (mlSmellTypeChart) mlSmellTypeChart.destroy();
    if (traditionalSmellTypeChart) traditionalSmellTypeChart.destroy();
    if (vulnTypeChart) vulnTypeChart.destroy();
    if (vulnSeverityChart) vulnSeverityChart.destroy();

    devCommitsChart = new Chart(document.getElementById('devCommitsChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Commits',
                data: commits,
                backgroundColor: 'rgba(99, 102, 241, 0.7)',
                borderColor: '#6366f1',
                borderWidth: 1
            }]
        },
        options: chartOptions()
    });

    devBugsChart = new Chart(document.getElementById('devBugsChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Bug Introduced (R-SZZ)',
                    data: bugIntro,
                    backgroundColor: 'rgba(245, 158, 11, 0.75)',
                    borderColor: '#f59e0b',
                    borderWidth: 1
                },
                {
                    label: 'Bug-Fix Commits',
                    data: bugFix,
                    backgroundColor: 'rgba(16, 185, 129, 0.75)',
                    borderColor: '#10b981',
                    borderWidth: 1
                }
            ]
        },
        options: chartOptions()
    });

    devChurnChart = new Chart(document.getElementById('devChurnChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Lines Added',
                    data: linesAdded,
                    backgroundColor: 'rgba(56, 189, 248, 0.75)',
                    borderColor: '#38bdf8',
                    borderWidth: 1
                },
                {
                    label: 'Lines Deleted',
                    data: linesDeleted,
                    backgroundColor: 'rgba(244, 63, 94, 0.75)',
                    borderColor: '#f43f5e',
                    borderWidth: 1
                }
            ]
        },
        options: chartOptions()
    });

    devRoleChart = new Chart(document.getElementById('devRoleChart').getContext('2d'), {
        type: 'doughnut',
        data: {
            labels: Object.keys(roleCounts),
            datasets: [{
                data: Object.values(roleCounts),
                backgroundColor: ['#6366f1', '#f59e0b', '#ec4899', '#10b981', '#38bdf8']
            }]
        },
        options: {
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#fff' }
                }
            }
        }
    });

    const timelineCanvas = document.getElementById('devSentimentTimelineChart');
    if (timelineCanvas && currentProject && Array.isArray(currentProject.time_windows)) {
        const windows = currentProject.time_windows || [];
        const timelineLabels = windows.map((w) => String(w.label || w.id || '').slice(0, 23));
        const topIds = top.slice(0, 5).map((d) => d.id);
        const palette = ['#22d3ee', '#a78bfa', '#f59e0b', '#34d399', '#fb7185'];
        const datasets = topIds.map((devId, idx) => {
            const points = windows.map((w) => {
                const row = (w.developers || []).find((d) => d.id === devId);
                return row ? Number(row.sentiment_score || 0) : null;
            });
            const label = (top.find((d) => d.id === devId)?.aliases?.[0]) || devId.split('@')[0];
            return {
                label,
                data: points,
                borderColor: palette[idx % palette.length],
                backgroundColor: 'transparent',
                borderWidth: 2,
                spanGaps: true,
                tension: 0.2
            };
        });
        devSentimentTimelineChart = new Chart(timelineCanvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: timelineLabels,
                datasets: datasets.length ? datasets : [{
                    label: 'No developer sentiment data',
                    data: [0],
                    borderColor: '#64748b'
                }]
            },
            options: chartOptions()
        });
    }

    const mlEntries = Object.entries(mlSmellCounts).sort((a, b) => b[1] - a[1]);
    const tradEntries = Object.entries(traditionalSmellCounts).sort((a, b) => b[1] - a[1]);
    const mlLabels = (mlEntries.length ? mlEntries : [['no_data', 0]]).map(([k]) => formatSmellLabel(k));
    const mlValues = (mlEntries.length ? mlEntries : [['no_data', 0]]).map(([, v]) => v);
    const tradLabels = (tradEntries.length ? tradEntries : [['no_data', 0]]).map(([k]) => formatSmellLabel(k));
    const tradValues = (tradEntries.length ? tradEntries : [['no_data', 0]]).map(([, v]) => v);

    mlSmellTypeChart = new Chart(document.getElementById('mlSmellTypeChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels: mlLabels,
            datasets: [{
                label: 'ML Smell Instances',
                data: mlValues,
                backgroundColor: 'rgba(236, 72, 153, 0.75)',
                borderColor: '#ec4899',
                borderWidth: 1
            }]
        },
        options: chartOptions()
    });

    traditionalSmellTypeChart = new Chart(document.getElementById('traditionalSmellTypeChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels: tradLabels,
            datasets: [{
                label: 'Traditional Smell Instances',
                data: tradValues,
                backgroundColor: 'rgba(99, 102, 241, 0.75)',
                borderColor: '#6366f1',
                borderWidth: 1
            }]
        },
        options: chartOptions()
    });

    renderSmellStatsList('mlSmellStats', mlEntries);
    renderSmellStatsList('traditionalSmellStats', tradEntries);

    const vulnTypeEntries = Object.entries(vulnerabilityCounts).sort((a, b) => b[1] - a[1]);
    const vulnSeverityEntries = Object.entries(vulnerabilitySeverityCounts).sort((a, b) => b[1] - a[1]);
    const vulnTypeLabels = (vulnTypeEntries.length ? vulnTypeEntries : [['no_data', 0]]).map(([k]) => formatSmellLabel(k));
    const vulnTypeValues = (vulnTypeEntries.length ? vulnTypeEntries : [['no_data', 0]]).map(([, v]) => v);
    const vulnSeverityLabels = (vulnSeverityEntries.length ? vulnSeverityEntries : [['no_data', 0]]).map(([k]) => formatSmellLabel(k));
    const vulnSeverityValues = (vulnSeverityEntries.length ? vulnSeverityEntries : [['no_data', 0]]).map(([, v]) => v);

    vulnTypeChart = new Chart(document.getElementById('vulnTypeChart').getContext('2d'), {
        type: 'bar',
        data: {
            labels: vulnTypeLabels,
            datasets: [{
                label: 'Vulnerability Instances',
                data: vulnTypeValues,
                backgroundColor: 'rgba(239, 68, 68, 0.75)',
                borderColor: '#ef4444',
                borderWidth: 1
            }]
        },
        options: chartOptions()
    });

    vulnSeverityChart = new Chart(document.getElementById('vulnSeverityChart').getContext('2d'), {
        type: 'doughnut',
        data: {
            labels: vulnSeverityLabels,
            datasets: [{
                data: vulnSeverityValues,
                backgroundColor: ['#ef4444', '#f59e0b', '#facc15', '#22c55e', '#64748b']
            }]
        },
        options: {
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#fff' }
                }
            }
        }
    });

    renderSmellStatsList('vulnTypeStats', vulnTypeEntries);
    renderSmellStatsList('vulnSeverityStats', vulnSeverityEntries);
}

function chartOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { labels: { color: '#fff' } }
        },
        scales: {
            x: {
                ticks: { color: '#cbd5e1', maxRotation: 45, minRotation: 20 },
                grid: { color: 'rgba(148, 163, 184, 0.15)' }
            },
            y: {
                ticks: { color: '#cbd5e1' },
                grid: { color: 'rgba(148, 163, 184, 0.15)' }
            }
        }
    };
}

function formatSmellLabel(raw) {
    return String(raw || '')
        .replace(/_/g, ' ')
        .toLowerCase()
        .replace(/\b\w/g, c => c.toUpperCase());
}

function renderSmellStatsList(containerId, entries) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!entries.length) {
        container.innerHTML = '<div class="smell-stats-empty">No smell data available</div>';
        return;
    }
    container.innerHTML = entries
        .map(([name, count]) => `<div class="smell-stats-row"><span>${formatSmellLabel(name)}</span><b>${count}</b></div>`)
        .join('');
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatTable3MetricValue(metric, rawValue) {
    if (rawValue === null || rawValue === undefined || rawValue === '') {
        return 'n/a';
    }
    const value = Number(rawValue);
    if (!Number.isFinite(value)) {
        return String(rawValue);
    }
    if (Number.isInteger(value)) {
        return String(value);
    }

    const metricName = String(metric || '').toLowerCase();
    const ratioLike = metricName.startsWith('perc.')
        || metricName.startsWith('ratio.')
        || metricName.includes('turnover')
        || metricName.includes('.truck')
        || metricName === 'st.congruence'
        || metricName === 'density';

    if (ratioLike) {
        return `${value.toFixed(4)} (${(value * 100).toFixed(1)}%)`;
    }
    return value.toFixed(4);
}

function renderCommunityMetricsReference(metricValues = {}) {
    const container = document.getElementById('communityMetricsReference');
    if (!container) return;

    container.innerHTML = COMMUNITY_METRICS_REFERENCE.map((section) => {
        const notes = (section.notes || [])
            .map((note) => `<p class="metrics-ref-note">${escapeHtml(note)}</p>`)
            .join('');

        const items = (section.items || []).map((item) => {
            const definition = escapeHtml(item.definition || 'No definition available.');
            const formula = item.formula ? `<div><b>Formula:</b> <code>${escapeHtml(item.formula)}</code></div>` : '';
            const compute = item.compute ? `<div><b>How to compute:</b> ${escapeHtml(item.compute)}</div>` : '';
            const metricKey = item.metric || 'metric';
            const metricValue = formatTable3MetricValue(metricKey, metricValues[metricKey]);
            return `
                <details class="metrics-ref-item">
                    <summary>
                        <code>${escapeHtml(metricKey)}</code>
                        <span>${definition}</span>
                        <b class="metrics-ref-value">${escapeHtml(metricValue)}</b>
                    </summary>
                    <div class="metrics-ref-body">
                        <div><b>Current window value:</b> ${escapeHtml(metricValue)}</div>
                        <div><b>Definition:</b> ${definition}</div>
                        ${formula}
                        ${compute}
                    </div>
                </details>
            `;
        }).join('');

        return `
            <section class="metrics-ref-section">
                <h4>${escapeHtml(section.title || 'Section')}</h4>
                ${notes}
                <div class="metrics-ref-list">
                    ${items}
                </div>
            </section>
        `;
    }).join('');
}
