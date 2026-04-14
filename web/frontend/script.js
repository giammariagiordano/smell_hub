const API_URL = window.location.origin;
let currentProject = null;
let currentWindowId = null;
let smellChart = null;
let devCommitsChart = null;
let devBugsChart = null;
let devChurnChart = null;
let devRoleChart = null;
let abandonedRoleChart = null;
let devSentimentTimelineChart = null;
let mlSmellTypeChart = null;
let traditionalSmellTypeChart = null;
let vulnTypeChart = null;
let vulnSeverityChart = null;
let overallMetricTrendChart = null;
let projectRoleDistributionChart = null;
let projectRoleTurnoverChart = null;
let globalRoleDistributionChart = null;
let globalRoleTurnoverChart = null;
let snapshotNetworkChart = null;
let overallNetworkChart = null;
const topicGraphInstances = new Map();
const topicExplorerState = new Map();
let cachedProjects = [];
let addRepoPreviewIndex = 0;
let addAnalyzeBtn = null;
let addProjectBtnModal = null;

const ROLE_COLOR_MAP = {
    'AI/ML Engineer': '#ec4899',
    'Software Engineer': '#3b82f6',
    'Hybrid': '#f59e0b',
    'Unknown': '#64748b',
};

const ROLE_ORDER = ['Software Engineer', 'AI/ML Engineer', 'Hybrid'];
const ROLE_FILTER_OPTIONS = [
    { key: 'Software Engineer', label: 'SE' },
    { key: 'AI/ML Engineer', label: 'ML' },
    { key: 'Hybrid', label: 'Hybrid' },
];
const CONFLICT_FILTER_OPTIONS = [
    { key: 'Software Engineer', label: 'SE x SE' },
    { key: 'AI/ML Engineer', label: 'ML x ML' },
    { key: 'Hybrid', label: 'Hybrid x Hybrid' },
    { key: 'Software Engineer x AI/ML Engineer', label: 'SE x ML' },
    { key: 'Software Engineer x Hybrid', label: 'SE x Hybrid' },
    { key: 'AI/ML Engineer x Hybrid', label: 'ML x Hybrid' },
    { key: 'Software Engineer x AI/ML Engineer x Hybrid', label: 'SE x ML x Hybrid' },
    { key: 'Unknown', label: 'Unclassified' },
];
const TOPIC_SECTION_OPTIONS = [
    { key: 'role_topics', label: 'Role Topics' },
    { key: 'developer_topics', label: 'Developer Topics' },
];

function normalizeRoleLabel(classification) {
    const role = String(classification || '').trim().toLowerCase();
    if (role.includes('hybrid')) return 'Hybrid';
    if (role.includes('ai') || role.includes('ml')) return 'AI/ML Engineer';
    if (role.includes('software engineer') || role === 'software' || /\bse\b/.test(role)) return 'Software Engineer';
    return 'Unknown';
}

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
const homeLogo = document.getElementById('homeLogo');
const addProjectBtn = document.getElementById('addProjectBtn');
const exportAllProjectsBtn = document.getElementById('exportAllProjectsBtn');
const deleteAllProjectsBtn = document.getElementById('deleteAllProjectsBtn');
const addProjectModal = document.getElementById('addProjectModal');
const addProjectForm = document.getElementById('addProjectForm');
const backBtn = document.getElementById('backBtn');
const prevProjectBtn = document.getElementById('prevProjectBtn');
const nextProjectBtn = document.getElementById('nextProjectBtn');
const projectPositionLabel = document.getElementById('projectPositionLabel');
const exportCsvBtn = document.getElementById('exportCsvBtn');
const exportCsvAllBtn = document.getElementById('exportCsvAllBtn');
const projectListSection = document.getElementById('projectListSection');
const projectDetailSection = document.getElementById('projectDetailSection');
const reanalyzeBtn = document.getElementById('reanalyzeBtn');
const timeWindowSelect = document.getElementById('timeWindowSelect');
const timeWindowLabel = document.getElementById('timeWindowLabel');
const prevWindowBtn = document.getElementById('prevWindowBtn');
const nextWindowBtn = document.getElementById('nextWindowBtn');
const analysisEta = document.getElementById('analysisEta');
const snapshotTabBtn = document.getElementById('snapshotTabBtn');
const overallTabBtn = document.getElementById('overallTabBtn');
const snapshotTabPanel = document.getElementById('snapshotTabPanel');
const overallTabPanel = document.getElementById('overallTabPanel');
const overallMetricSelect = document.getElementById('overallMetricSelect');
const overallMetricsTimelineTable = document.getElementById('overallMetricsTimelineTable');
const overallDevelopersSummaryTable = document.getElementById('overallDevelopersSummaryTable');
const projectRoleIntervalSelect = document.getElementById('projectRoleIntervalSelect');
const projectRoleTurnoverTable = document.getElementById('projectRoleTurnoverTable');
const globalRoleIntervalSelect = document.getElementById('globalRoleIntervalSelect');
const globalRoleTurnoverTable = document.getElementById('globalRoleTurnoverTable');
const analyzeProjectTopicsBtn = document.getElementById('analyzeProjectTopicsBtn');
const analyzeGlobalTopicsBtn = document.getElementById('analyzeGlobalTopicsBtn');
const projectTopicsStatus = document.getElementById('projectTopicsStatus');
const projectTopicsTree = document.getElementById('projectTopicsTree');
const globalTopicsStatus = document.getElementById('globalTopicsStatus');
const globalTopicsTree = document.getElementById('globalTopicsTree');
const llmApiKeyInput = document.getElementById('llmApiKeyInput');
const llmApiKeyHint = document.getElementById('llmApiKeyHint');
const githubTokenInput = document.getElementById('githubTokenInput');
const githubTokenHint = document.getElementById('githubTokenHint');
const llmModelInput = document.getElementById('llmModelInput');
const llmRunsInput = document.getElementById('llmRunsInput');
const llmOrganizationInput = document.getElementById('llmOrganizationInput');
const llmProjectInput = document.getElementById('llmProjectInput');
const llmEndpointInput = document.getElementById('llmEndpointInput');
const saveLlmSettingsBtn = document.getElementById('saveLlmSettingsBtn');
const clearLlmKeyBtn = document.getElementById('clearLlmKeyBtn');
const llmSettingsStatus = document.getElementById('llmSettingsStatus');
const projUrlsInput = document.getElementById('projUrls');
const prevRepoInListBtn = document.getElementById('prevRepoInListBtn');
const nextRepoInListBtn = document.getElementById('nextRepoInListBtn');
const repoListPositionLabel = document.getElementById('repoListPositionLabel');
const repoListCurrentValue = document.getElementById('repoListCurrentValue');
const projCsvFileInput = document.getElementById('projCsvFile');
const importCsvBtn = document.getElementById('importCsvBtn');
const importCsvAnalyzeBtn = document.getElementById('importCsvAnalyzeBtn');
const addProjectAnalyzeBtn = document.getElementById('addProjectAnalyzeBtn');
const bulkImportStatus = document.getElementById('bulkImportStatus');
const IMPORT_ETA_KEY = 'bulk_import_sec_per_repo_v1';
const LLM_ANALYSIS_TIMEOUT_MS = 180000;

async function fetchWithTimeout(url, options = {}, timeoutMs = LLM_ANALYSIS_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

function currentLlmRuns() {
    return Math.max(1, Math.min(7, Number(llmRunsInput?.value || 1) || 1));
}

function computeLlmAnalysisTimeoutMs(mode = 'project') {
    const runs = currentLlmRuns();
    const perRunMs = mode === 'global' ? 240000 : 180000;
    const judgeMs = mode === 'global' ? 240000 : 180000;
    const baseMs = mode === 'global' ? 240000 : 120000;
    const total = baseMs + (runs * perRunMs) + judgeMs;
    return Math.max(LLM_ANALYSIS_TIMEOUT_MS, Math.min(total, 3600000));
}

function ensureAddAnalyzeBtn() {
    if (!addAnalyzeBtn) {
        addAnalyzeBtn = addProjectAnalyzeBtn || null;
    }
    return addAnalyzeBtn;
}

function ensureAddProjectBtnModal() {
    if (!addProjectBtnModal) {
        addProjectBtnModal = addProjectForm?.querySelector('button[type="submit"]') || null;
    }
    return addProjectBtnModal;
}

function parseRepoUrlList(rawValue) {
    return String(rawValue || '')
        .split(/\r?\n|,/)
        .map(x => x.trim())
        .filter(Boolean);
}

function renderRepoListPreview() {
    const urls = parseRepoUrlList(projUrlsInput?.value || '');
    const total = urls.length;
    if (total <= 0) {
        addRepoPreviewIndex = 0;
        if (repoListPositionLabel) repoListPositionLabel.innerText = 'Repo 0/0';
        if (repoListCurrentValue) repoListCurrentValue.innerText = 'Current: n/a';
        if (prevRepoInListBtn) prevRepoInListBtn.disabled = true;
        if (nextRepoInListBtn) nextRepoInListBtn.disabled = true;
        return;
    }

    if (addRepoPreviewIndex >= total) addRepoPreviewIndex = total - 1;
    if (addRepoPreviewIndex < 0) addRepoPreviewIndex = 0;
    if (repoListPositionLabel) repoListPositionLabel.innerText = `Repo ${addRepoPreviewIndex + 1}/${total}`;
    if (repoListCurrentValue) repoListCurrentValue.innerText = `Current: ${urls[addRepoPreviewIndex]}`;
    if (prevRepoInListBtn) prevRepoInListBtn.disabled = addRepoPreviewIndex <= 0;
    if (nextRepoInListBtn) nextRepoInListBtn.disabled = addRepoPreviewIndex >= total - 1;
}

function formatEta(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return 'n/a';
    if (value === 0) return '0s';
    const s = Math.round(value);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
}

function readImportSecPerRepo() {
    const fromStorage = Number(localStorage.getItem(IMPORT_ETA_KEY));
    if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;
    return 6.0;
}

function writeImportSecPerRepo(value) {
    const v = Number(value);
    if (!Number.isFinite(v) || v <= 0) return;
    const current = readImportSecPerRepo();
    const blended = (current * 0.7) + (v * 0.3);
    localStorage.setItem(IMPORT_ETA_KEY, String(blended.toFixed(3)));
}

function setBulkImportStatus(message, isError = false) {
    if (!bulkImportStatus) return;
    bulkImportStatus.style.color = isError ? '#fda4af' : '#94a3b8';
    bulkImportStatus.innerText = message || '';
}

function estimateCsvRowsFromText(text) {
    const rawLines = String(text || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    if (rawLines.length <= 1) return 0;
    return Math.max(rawLines.length - 1, 0);
}

function renderAnalysisEta(project) {
    if (!analysisEta || !project) return;
    const progress = Number(project.analysis_progress_pct || 0);
    if (project.analysis_status === 'Running') {
        const windowPart = (project.analysis_window_total || 0) > 0
            ? ` | Window ${project.analysis_window_index || 0}/${project.analysis_window_total || 0}`
            : '';
        analysisEta.innerText = `Progress: ${progress.toFixed(1)}% | ETA: ${formatEta(project.analysis_eta_seconds)}${windowPart}`;
    } else if (project.analysis_status === 'Completed') {
        analysisEta.innerText = 'Progress: 100.0% | ETA: completed';
    } else {
        analysisEta.innerText = `Progress: ${progress.toFixed(1)}% | ETA: n/a`;
    }
}

function switchDetailTab(tabName) {
    const isOverall = tabName === 'overall';
    if (snapshotTabPanel) snapshotTabPanel.classList.toggle('hidden', isOverall);
    if (overallTabPanel) overallTabPanel.classList.toggle('hidden', !isOverall);
    if (snapshotTabBtn) snapshotTabBtn.classList.toggle('active', !isOverall);
    if (overallTabBtn) overallTabBtn.classList.toggle('active', isOverall);
    if (isOverall && currentProject) {
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                renderOverallStats(currentProject);
            });
        });
    }
}

if (snapshotTabBtn) snapshotTabBtn.onclick = () => switchDetailTab('snapshot');
if (overallTabBtn) overallTabBtn.onclick = () => switchDetailTab('overall');

function metricLabelFromKey(key) {
    return String(key || '')
        .replace(/^stqf\./, 'STQF: ')
        .replace(/_/g, ' ')
        .replace(/\./g, ' ');
}

function collectOverallWindows(project) {
    if (!project) return [];
    const windows = Array.isArray(project.time_windows) ? project.time_windows : [];
    if (windows.length) return windows;
    const fallbackMetrics = (project.metrics && project.metrics.length > 0) ? project.metrics[0] : null;
    if (!fallbackMetrics) return [];
    return [{
        id: 'latest',
        label: 'Current Snapshot',
        developers: project.developers || [],
        metrics: fallbackMetrics,
        collaboration_edges: project.collaboration_edges || [],
    }];
}

function safeNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
}

function parseDateValue(value) {
    if (!value) return null;
    const dt = new Date(value);
    return Number.isNaN(dt.getTime()) ? null : dt;
}

function formatDateTime(value) {
    const dt = parseDateValue(value);
    if (!dt) return '';
    return dt.toISOString().replace('T', ' ').slice(0, 19);
}

function formatMonthLabel(date) {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    return `${year}-${month}`;
}

function startOfUtcQuarter(date) {
    const quarterMonth = Math.floor(date.getUTCMonth() / 3) * 3;
    return new Date(Date.UTC(date.getUTCFullYear(), quarterMonth, 1));
}

function startOfUtcYear(date) {
    return new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
}

function getIntervalStart(date, interval) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null;
    if (interval === 'yearly') return startOfUtcYear(date);
    if (interval === 'quarterly') return startOfUtcQuarter(date);
    return floorToUtcMonth(date);
}

function formatIntervalBucketLabel(date, interval) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return 'n/a';
    if (interval === 'yearly') return String(date.getUTCFullYear());
    if (interval === 'quarterly') {
        const q = Math.floor(date.getUTCMonth() / 3) + 1;
        return `${date.getUTCFullYear()} Q${q}`;
    }
    return formatMonthLabel(date);
}

function createRoleCountSeed() {
    return ROLE_ORDER.reduce((acc, role) => {
        acc[role] = 0;
        return acc;
    }, {});
}

function compareDateAsc(a, b) {
    const tsA = a instanceof Date ? a.getTime() : 0;
    const tsB = b instanceof Date ? b.getTime() : 0;
    return tsA - tsB;
}

function buildRoleTimelineData(projects, interval = 'quarterly', scope = 'project') {
    const bucketMap = new Map();

    (projects || []).forEach((project) => {
        const windows = collectOverallWindows(project);
        windows.forEach((windowItem) => {
            const start = getWindowStartDate(windowItem);
            if (!start) return;

            const bucketStart = getIntervalStart(start, interval);
            if (!bucketStart) return;
            const bucketKey = bucketStart.toISOString();

            if (!bucketMap.has(bucketKey)) {
                bucketMap.set(bucketKey, {
                    key: bucketKey,
                    start: bucketStart,
                    label: formatIntervalBucketLabel(bucketStart, interval),
                    developerMap: new Map(),
                    sourceWindows: [],
                });
            }

            bucketMap.get(bucketKey).sourceWindows.push({
                projectId: project?.id || '',
                projectName: project?.name || '',
                windowItem,
                start,
            });
        });
    });

    const buckets = Array.from(bucketMap.values()).sort((a, b) => compareDateAsc(a.start, b.start));

    buckets.forEach((bucket) => {
        bucket.sourceWindows.sort((a, b) => compareDateAsc(a.start, b.start));
        bucket.sourceWindows.forEach((entry) => {
            (entry.windowItem?.developers || []).forEach((dev) => {
                const developerId = String(dev?.id || '').trim();
                if (!developerId) return;

                const scopedDeveloperKey = scope === 'global'
                    ? `${entry.projectId}::${developerId}`
                    : developerId;

                bucket.developerMap.set(scopedDeveloperKey, {
                    scopedDeveloperKey,
                    developerId,
                    projectId: entry.projectId,
                    projectName: entry.projectName,
                    role: normalizeRoleLabel(dev?.classification),
                    sourceWindowId: entry.windowItem?.id || '',
                    sourceWindowLabel: entry.windowItem?.label || '',
                });
            });
        });

        const roleCounts = createRoleCountSeed();
        bucket.developerMap.forEach((devRow) => {
            if (ROLE_ORDER.includes(devRow.role)) {
                roleCounts[devRow.role] += 1;
            }
        });
        bucket.roleCounts = roleCounts;
    });

    let previousDeveloperMap = null;
    buckets.forEach((bucket) => {
        const turnoverByRole = createRoleCountSeed();
        const transitionRows = [];

        if (previousDeveloperMap) {
            bucket.developerMap.forEach((currentDev) => {
                const previousDev = previousDeveloperMap.get(currentDev.scopedDeveloperKey);
                if (!previousDev) return;
                const fromRole = normalizeRoleLabel(previousDev.role);
                const toRole = normalizeRoleLabel(currentDev.role);
                if (!ROLE_ORDER.includes(toRole) || fromRole === toRole) return;

                turnoverByRole[toRole] += 1;
                transitionRows.push({
                    bucketLabel: bucket.label,
                    projectId: currentDev.projectId,
                    projectName: currentDev.projectName,
                    developerId: currentDev.developerId,
                    fromRole,
                    toRole,
                });
            });
        }

        bucket.turnoverByRole = turnoverByRole;
        bucket.transitionRows = transitionRows.sort((a, b) => {
            const projectCmp = String(a.projectName || '').localeCompare(String(b.projectName || ''));
            if (projectCmp !== 0) return projectCmp;
            return String(a.developerId || '').localeCompare(String(b.developerId || ''));
        });
        previousDeveloperMap = bucket.developerMap;
    });

    return buckets;
}

function destroyChartInstance(instance) {
    if (instance && typeof instance.destroy === 'function') {
        instance.destroy();
    }
}

function stackedBarOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { labels: { color: '#fff' } }
        },
        scales: {
            x: {
                stacked: true,
                ticks: { color: '#cbd5e1', maxRotation: 45, minRotation: 20 },
                grid: { color: 'rgba(148, 163, 184, 0.12)' }
            },
            y: {
                stacked: true,
                beginAtZero: true,
                ticks: { color: '#cbd5e1', precision: 0 },
                grid: { color: 'rgba(148, 163, 184, 0.12)' }
            }
        }
    };
}

function renderRoleTurnoverTable(tableEl, buckets, scope = 'project') {
    if (!tableEl) return;
    const rows = (buckets || []).flatMap((bucket) => bucket.transitionRows || []);

    if (!rows.length) {
        tableEl.innerHTML = '<tr><td style="padding:0.7rem; color:#94a3b8;">No role transitions detected for the selected interval.</td></tr>';
        return;
    }

    const headers = scope === 'global'
        ? ['Time Window', 'Project', 'Developer', 'From', 'To']
        : ['Time Window', 'Developer', 'From', 'To'];

    const head = `<thead><tr>${headers.map((label) => `<th>${escapeHtml(label)}</th>`).join('')}</tr></thead>`;
    const body = rows.map((row) => {
        const cells = [
            `<td>${escapeHtml(row.bucketLabel)}</td>`,
        ];
        if (scope === 'global') {
            cells.push(`<td>${escapeHtml(row.projectName || '-')}</td>`);
        }
        cells.push(`<td>${escapeHtml(row.developerId)}</td>`);
        cells.push(`<td>${escapeHtml(row.fromRole)}</td>`);
        cells.push(`<td>${escapeHtml(row.toRole)}</td>`);
        return `<tr>${cells.join('')}</tr>`;
    }).join('');

    tableEl.innerHTML = `${head}<tbody>${body}</tbody>`;
}

function renderRoleEvolutionCharts({
    projects,
    interval,
    scope,
    distributionCanvasId,
    turnoverCanvasId,
    distributionChart,
    turnoverChart,
    tableEl,
}) {
    const buckets = buildRoleTimelineData(projects, interval, scope);
    const labels = buckets.map((bucket) => bucket.label);
    const distributionDatasets = ROLE_ORDER.map((role) => ({
        label: role,
        data: buckets.map((bucket) => Number(bucket.roleCounts?.[role] || 0)),
        backgroundColor: ROLE_COLOR_MAP[role] || ROLE_COLOR_MAP.Unknown,
        borderColor: ROLE_COLOR_MAP[role] || ROLE_COLOR_MAP.Unknown,
        borderWidth: 1,
    }));
    const turnoverDatasets = ROLE_ORDER.map((role) => ({
        label: `Changed to ${role}`,
        data: buckets.map((bucket) => Number(bucket.turnoverByRole?.[role] || 0)),
        backgroundColor: ROLE_COLOR_MAP[role] || ROLE_COLOR_MAP.Unknown,
        borderColor: ROLE_COLOR_MAP[role] || ROLE_COLOR_MAP.Unknown,
        borderWidth: 1,
    }));

    const distributionCtx = document.getElementById(distributionCanvasId)?.getContext('2d');
    const turnoverCtx = document.getElementById(turnoverCanvasId)?.getContext('2d');

    destroyChartInstance(distributionChart);
    destroyChartInstance(turnoverChart);

    let nextDistributionChart = null;
    let nextTurnoverChart = null;

    if (distributionCtx) {
        nextDistributionChart = new Chart(distributionCtx, {
            type: 'bar',
            data: {
                labels: labels.length ? labels : ['No Data'],
                datasets: distributionDatasets,
            },
            options: stackedBarOptions(),
        });
    }

    if (turnoverCtx) {
        nextTurnoverChart = new Chart(turnoverCtx, {
            type: 'bar',
            data: {
                labels: labels.length ? labels : ['No Data'],
                datasets: turnoverDatasets,
            },
            options: stackedBarOptions(),
        });
    }

    renderRoleTurnoverTable(tableEl, buckets, scope);
    return {
        distributionChart: nextDistributionChart,
        turnoverChart: nextTurnoverChart,
        buckets,
    };
}

function formatTopicTimestamp(value) {
    if (!value) return '';
    const dt = parseDateValue(value);
    if (!dt) return '';
    return dt.toISOString().slice(0, 19).replace('T', ' ');
}

function getTopicExplorerState(scopeKey) {
    const key = String(scopeKey || 'global');
    if (!topicExplorerState.has(key)) {
        topicExplorerState.set(key, {
            selectedRoleFilters: new Set(),
            selectedConflictFilters: new Set(),
            selectedTopicSections: new Set(),
            selectedNodeIds: {
                topics: '',
                conflicts: '',
            },
        });
    }
    return topicExplorerState.get(key);
}

function normalizeCommunityKey(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parts = raw.split(/\s*x\s*/i).map((part) => normalizeRoleLabel(part)).filter((part) => ROLE_ORDER.includes(part));
    if (!parts.length) {
        const normalizedRole = normalizeRoleLabel(raw);
        return ROLE_ORDER.includes(normalizedRole) ? normalizedRole : '';
    }
    const unique = Array.from(new Set(parts));
    if (unique.length === 1) return unique[0];
    return unique.sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b)).join(' x ');
}

function conflictCommunityKey(conflict) {
    const payloadRoles = Array.isArray(conflict?.participant_roles)
        ? conflict.participant_roles.map((role) => normalizeRoleLabel(role)).filter((role) => ROLE_ORDER.includes(role))
        : [];
    const roles = payloadRoles.length
        ? payloadRoles
        : [
            normalizeRoleLabel(conflict?.developer_role),
            normalizeRoleLabel(conflict?.counterpart_role),
        ].filter((role) => ROLE_ORDER.includes(role));
    if (roles.length) {
        return normalizeCommunityKey(roles.join(' x ')) || 'Unknown';
    }
    return normalizeCommunityKey(conflict?.role_combination || '') || 'Unknown';
}

function communityFilterLabel(key) {
    const found = ROLE_FILTER_OPTIONS.find((item) => item.key === key)
        || CONFLICT_FILTER_OPTIONS.find((item) => item.key === key);
    return found?.label || key;
}

function conflictFilterLabel(key) {
    const found = CONFLICT_FILTER_OPTIONS.find((item) => item.key === key);
    return found?.label || communityFilterLabel(key);
}

function potentialConflictCommunityKey(thread) {
    const roles = Array.isArray(thread?.participant_roles)
        ? thread.participant_roles.map((role) => normalizeRoleLabel(role)).filter((role) => ROLE_ORDER.includes(role))
        : [];
    const unique = Array.from(new Set(roles));
    if (!unique.length) return 'Unknown';
    if (unique.length === 1) return unique[0] || 'Unknown';
    return unique.sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b)).join(' x ') || 'Unknown';
}

function communityKeyDisplayLabel(key, context = 'topic') {
    const normalized = normalizeCommunityKey(key);
    const found = context === 'conflict'
        ? CONFLICT_FILTER_OPTIONS.find((item) => item.key === normalized)
        : ROLE_FILTER_OPTIONS.find((item) => item.key === normalized);
    if (found) return found.label;
    const parts = String(normalized || '')
        .split(/\s*x\s*/i);
    if (context === 'conflict' && parts.length === 1 && parts[0]) {
        return conflictFilterLabel(parts[0]);
    }
    const displayParts = parts
        .map((part) => communityFilterLabel(part))
        .filter(Boolean);
    return displayParts.length ? displayParts.join(' x ') : String(key || 'Community');
}

function allRoleFiltersSelected(selectedFilters) {
    return ROLE_FILTER_OPTIONS.every((item) => selectedFilters.has(item.key));
}

function allConflictFiltersSelected(selectedFilters) {
    return CONFLICT_FILTER_OPTIONS.every((item) => selectedFilters.has(item.key));
}

function formatSourceBreakdown(sourceBreakdown) {
    const entries = Object.entries(sourceBreakdown || {}).filter(([, value]) => Number(value) > 0);
    if (!entries.length) return '';
    return entries
        .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
        .map(([key, value]) => `${key}: ${Number(value)}`)
        .join(' | ');
}

function mixColor(colorA, colorB) {
    const a = String(colorA || '#64748b').replace('#', '');
    const b = String(colorB || '#64748b').replace('#', '');
    const aa = a.length === 6 ? a : '64748b';
    const bb = b.length === 6 ? b : '64748b';
    const toRgb = (value) => [0, 2, 4].map((idx) => parseInt(value.slice(idx, idx + 2), 16));
    const ar = toRgb(aa);
    const br = toRgb(bb);
    const mixed = ar.map((value, index) => Math.round((value + br[index]) / 2));
    return `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}

function communityColor(key) {
    const normalized = normalizeCommunityKey(key);
    if (ROLE_COLOR_MAP[normalized]) return ROLE_COLOR_MAP[normalized];
    const parts = normalized.split(' x ').filter(Boolean);
    if (parts.length === 2) {
        return mixColor(ROLE_COLOR_MAP[parts[0]], ROLE_COLOR_MAP[parts[1]]);
    }
    return ROLE_COLOR_MAP.Unknown;
}

function shortDeveloperLabel(value) {
    const raw = String(value || '').trim();
    if (!raw) return 'developer';
    return raw.length > 28 ? `${raw.slice(0, 25)}...` : raw;
}

function subtopicDisplayEvidenceCount(subtopic) {
    return Math.max(0, Number(subtopic?.evidence_count || 0));
}

function topicDisplayEvidenceCount(topic) {
    const subtopics = Array.isArray(topic?.subtopics) ? topic.subtopics : [];
    if (subtopics.length) {
        return subtopics.reduce((sum, subtopic) => sum + subtopicDisplayEvidenceCount(subtopic), 0);
    }
    return Math.max(0, Number(topic?.evidence_count || 0));
}

function formatGraphLabel(title, subtitle = '') {
    const top = String(title || '').trim() || 'Node';
    const bottom = String(subtitle || '').trim();
    return bottom ? `${top}\n${bottom}` : top;
}

function topicExtractionFailureLabel(result, fallback = 'No topics extracted') {
    const status = String(result?.status || '').trim().toLowerCase();
    const error = String(result?.error || '').trim();
    if (status === 'error') {
        return error ? 'Topic extraction failed' : 'Topic extraction error';
    }
    if (status.includes('skipped')) return 'Topic extraction skipped';
    return fallback;
}

function renderTraceLinks(links, emptyMessage = '') {
    const rows = Array.isArray(links) ? links.filter(Boolean) : [];
    if (!rows.length) {
        return emptyMessage ? `<div class="topic-links-empty">${escapeHtml(emptyMessage)}</div>` : '';
    }
    return `
        <div class="topic-trace-links">
            ${rows.map((link) => {
                const label = String(link?.label || link?.source_id || 'Source');
                const meta = [String(link?.source_type || '').trim(), link?.is_open ? 'open' : 'closed']
                    .filter(Boolean)
                    .join(' | ');
                const href = String(link?.url || '').trim();
                const body = href
                    ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`
                    : `<span>${escapeHtml(label)}</span>`;
                return `
                    <div class="topic-trace-link">
                        ${body}
                        ${meta ? `<div class="topic-trace-meta">${escapeHtml(meta)}</div>` : ''}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderPrimaryTraceLink(link) {
    if (!link) return '';
    const label = String(link?.label || link?.source_id || 'Conflict thread');
    const href = String(link?.url || '').trim();
    const meta = [String(link?.source_type || '').trim(), link?.is_open ? 'open' : 'closed']
        .filter(Boolean)
        .join(' | ');
    return `
        <div class="topic-primary-link">
            <div class="topic-primary-link-label">Conflict Thread</div>
            <div class="topic-primary-link-body">
                ${href
                    ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`
                    : `<span>${escapeHtml(label)}</span>`}
                ${meta ? `<div class="topic-trace-meta">${escapeHtml(meta)}</div>` : ''}
            </div>
        </div>
    `;
}

function renderPotentialConflictThreads(threads) {
    const rows = Array.isArray(threads) ? threads.filter(Boolean) : [];
    if (!rows.length) return '';
    return `
        <div class="topic-potential-list">
            ${rows.map((thread) => {
                const href = String(thread?.thread_url || '').trim();
                const label = String(thread?.thread_label || thread?.thread_id || 'Potential conflict thread');
                const signals = Array.isArray(thread?.matched_signals) ? thread.matched_signals.filter(Boolean) : [];
                const participants = Array.isArray(thread?.participant_ids) ? thread.participant_ids.filter(Boolean) : [];
                return `
                    <div class="topic-potential-item">
                        <div class="topic-potential-title">
                            ${href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>` : escapeHtml(label)}
                        </div>
                        ${thread?.summary ? `<div class="topic-potential-summary">${escapeHtml(thread.summary)}</div>` : ''}
                        <div class="topic-potential-meta">
                            ${thread?.source_type ? `<span>${escapeHtml(thread.source_type)}</span>` : ''}
                            <span>${thread?.is_open ? 'open' : 'closed'}</span>
                            ${participants.length ? `<span>${escapeHtml(participants.join(', '))}</span>` : ''}
                            ${signals.length ? `<span>signals: ${escapeHtml(signals.join(', '))}</span>` : ''}
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function extractAvailableTopicFilterKeys(result) {
    const availableRoles = new Set();
    const availableConflicts = new Set();
    (result?.roles || []).forEach((roleRow) => {
        const key = normalizeCommunityKey(roleRow?.role);
        if (key) availableRoles.add(key);
    });
    (result?.developers || []).forEach((dev) => {
        const key = normalizeCommunityKey(dev?.role);
        if (key) availableRoles.add(key);
    });
    (result?.conflicts || []).forEach((conflict) => {
        const key = conflictCommunityKey(conflict);
        if (key) availableConflicts.add(key);
    });
    (result?.potential_conflict_threads || []).forEach((thread) => {
        const key = potentialConflictCommunityKey(thread);
        if (key) availableConflicts.add(key);
    });
    return { availableRoles, availableConflicts };
}

function buildTopicExplorerGraph(result, options = {}) {
    const scopeKey = String(options.scopeKey || 'scope');
    const mode = String(options.mode || 'topics');
    const selectedRoleFilters = options.selectedRoleFilters instanceof Set
        ? options.selectedRoleFilters
        : new Set();
    const selectedConflictFilters = options.selectedConflictFilters instanceof Set
        ? options.selectedConflictFilters
        : new Set();
    const selectedTopicSections = options.selectedTopicSections instanceof Set
        ? options.selectedTopicSections
        : new Set();
    const prefix = `${scopeKey}_${mode}`.replace(/[^a-zA-Z0-9_-]+/g, '_');
    const metadata = {};
    const nodes = [];
    const edges = [];
    let nodeSeq = 0;

    function addNode(key, label, extra = {}, meta = {}) {
        nodeSeq += 1;
        const id = `${prefix}:${key}:${nodeSeq}`;
        nodes.push({
            id,
            label,
            shape: extra.shape || 'box',
            font: { color: '#f8fafc', face: 'Outfit', size: extra.fontSize || 15, multi: false, bold: extra.bold ? '700 15px Outfit' : undefined },
            color: extra.color || { background: '#1e293b', border: '#475569' },
            margin: extra.margin || 10,
            widthConstraint: extra.widthConstraint || { maximum: 220 },
            level: Number.isFinite(extra.level) ? extra.level : undefined,
        });
        metadata[id] = meta;
        return id;
    }

    function attachEvidenceNodes(parentId, baseKey, payload = {}, style = {}) {
        const traceLinks = Array.isArray(payload?.traceLinks) ? payload.traceLinks.filter(Boolean) : [];
        const examples = Array.isArray(payload?.examples) ? payload.examples.filter((x) => String(x || '').trim()) : [];
        const signals = Array.isArray(payload?.matchedSignals) ? payload.matchedSignals.filter((x) => String(x || '').trim()) : [];
        const maxNodes = 10;
        const evidenceItems = [];

        traceLinks.forEach((link) => {
            const label = String(link?.label || link?.source_id || 'Evidence');
            evidenceItems.push({
                type: 'trace_link',
                title: label,
                summary: String(link?.source_type || ''),
                traceLinks: [link],
            });
        });

        examples.forEach((example, idx) => {
            evidenceItems.push({
                type: 'example',
                title: `Example ${idx + 1}`,
                summary: String(example || ''),
                traceLinks: [],
            });
        });

        signals.forEach((signal, idx) => {
            evidenceItems.push({
                type: 'signal',
                title: `Signal ${idx + 1}`,
                summary: String(signal || ''),
                traceLinks: [],
            });
        });

        if (!evidenceItems.length) return;

        const shown = evidenceItems.slice(0, maxNodes);
        shown.forEach((item, idx) => {
            const evId = addNode(
                `evidence:${baseKey}:${idx}`,
                formatGraphLabel(item.title, item.summary || 'evidence'),
                {
                    shape: 'box',
                    color: style.color || { background: '#0b1220', border: '#64748b' },
                    fontSize: 11,
                    widthConstraint: { maximum: 210 },
                    level: Number.isFinite(style.level) ? style.level : undefined,
                },
                {
                    type: 'evidence',
                    title: item.title,
                    summary: item.summary,
                    traceLinks: item.traceLinks || [],
                }
            );
            edges.push({ from: parentId, to: evId });
        });

        if (evidenceItems.length > shown.length) {
            const remaining = evidenceItems.length - shown.length;
            const moreId = addNode(
                `evidence:${baseKey}:more`,
                formatGraphLabel(`+${remaining} more`, 'evidences hidden'),
                {
                    shape: 'box',
                    color: style.color || { background: '#0b1220', border: '#64748b' },
                    fontSize: 11,
                    widthConstraint: { maximum: 180 },
                    level: Number.isFinite(style.level) ? style.level : undefined,
                },
                {
                    type: 'evidence',
                    title: 'Additional evidences',
                    summary: `${remaining} additional evidences are not shown in the graph for readability.`,
                }
            );
            edges.push({ from: parentId, to: moreId });
        }
    }

    const rootId = addNode(
        'root',
        formatGraphLabel(
            mode === 'conflicts' ? 'Conflict Explorer' : 'Topics Explorer',
            `${Number(result?.source_count || 0)} sources`
        ),
        { shape: 'box', color: { background: '#0f172a', border: '#38bdf8' }, fontSize: 20, margin: 16, widthConstraint: { maximum: 260 }, bold: true, level: 0 },
        {
            type: 'root',
            title: mode === 'conflicts' ? 'Conflict Explorer' : 'Topics Explorer',
            summary: mode === 'conflicts'
                ? 'Inspect confirmed conflicts and candidate threads grouped by community combination.'
                : 'Inspect role-level and developer-level interaction topics with traceability links.',
            taxonomyNotes: Array.isArray(result?.taxonomy_notes) ? result.taxonomy_notes.filter(Boolean) : [],
            sourceCount: Number(result?.source_count || 0),
            discussionSourceCount: Number(result?.discussion_source_count || 0),
            llmRunCount: Number(result?.llm_run_count || 1),
            judged: Boolean(result?.judged),
            model: String(result?.model || ''),
            judgeModel: String(result?.judge_model || ''),
            sourceBreakdownText: formatSourceBreakdown(result?.source_breakdown || {}),
            potentialConflictThreads: mode === 'conflicts' && Array.isArray(result?.potential_conflict_threads)
                ? result.potential_conflict_threads
                : [],
        }
    );

    const activeSingles = ROLE_ORDER.filter((role) => selectedRoleFilters.has(role));
    const roleRows = (result?.roles || []).filter((roleRow) => activeSingles.includes(normalizeRoleLabel(roleRow?.role)));
    if (mode === 'topics' && selectedTopicSections.has('role_topics') && roleRows.length) {
        const sectionId = addNode(
            'section:role-topics',
            formatGraphLabel('Role Topics', `${roleRows.length} communities`),
            { color: { background: '#111827', border: '#60a5fa' }, fontSize: 17, widthConstraint: { maximum: 240 }, bold: true, level: 1 },
            { type: 'section', title: 'Role Topics', summary: 'Topic and subtopic tree grouped by community.' }
        );
        edges.push({ from: rootId, to: sectionId });
        roleRows.forEach((roleRow) => {
            const role = normalizeRoleLabel(roleRow?.role);
            const roleId = addNode(
                `role:${role}`,
                formatGraphLabel(communityFilterLabel(role), `${Number(roleRow?.documents_count || 0)} docs`),
                { color: { background: communityColor(role), border: communityColor(role) }, widthConstraint: { maximum: 180 }, bold: true, level: 2 },
                {
                    type: 'role',
                    title: role,
                    summary: String(roleRow?.summary || ''),
                    documentsCount: Number(roleRow?.documents_count || 0),
                }
            );
            edges.push({ from: sectionId, to: roleId });
            const roleTopics = Array.isArray(roleRow?.topics) ? roleRow.topics : [];
            if (!roleTopics.length) {
                const emptyId = addNode(
                    `role-topic-empty:${role}`,
                    formatGraphLabel(topicExtractionFailureLabel(result), 'No role-level topics available'),
                    { color: { background: '#111827', border: '#64748b' }, fontSize: 12, widthConstraint: { maximum: 220 }, level: 3 },
                    {
                        type: 'empty',
                        title: `${role} Topics`,
                        role,
                        summary: String(result?.error || 'The analyzer returned no topic nodes for this role.'),
                    }
                );
                edges.push({ from: roleId, to: emptyId });
            }
            roleTopics.forEach((topic, topicIndex) => {
                const topicId = addNode(
                    `role-topic:${role}:${topicIndex}`,
                    formatGraphLabel(String(topic?.name || 'Topic'), `${topicDisplayEvidenceCount(topic)} evidences`),
                    { color: { background: '#1f2937', border: communityColor(role) }, widthConstraint: { maximum: 230 }, level: 3 },
                    {
                        type: 'topic',
                        title: String(topic?.name || 'Topic'),
                        role,
                        summary: String(topic?.summary || ''),
                        evidenceCount: topicDisplayEvidenceCount(topic),
                        traceLinks: topic?.trace_links || [],
                    }
                );
                edges.push({ from: roleId, to: topicId });
                (topic?.subtopics || []).forEach((subtopic, subIndex) => {
                    const subId = addNode(
                        `role-subtopic:${role}:${topicIndex}:${subIndex}`,
                        formatGraphLabel(String(subtopic?.name || 'Subtopic'), `${subtopicDisplayEvidenceCount(subtopic)} evidences`),
                        { shape: 'ellipse', color: { background: '#0f172a', border: communityColor(role) }, fontSize: 13, widthConstraint: { maximum: 210 }, level: 4 },
                        {
                            type: 'subtopic',
                            title: String(subtopic?.name || 'Subtopic'),
                            role,
                            summary: String(subtopic?.summary || ''),
                            evidenceCount: subtopicDisplayEvidenceCount(subtopic),
                            examples: subtopic?.examples || [],
                            traceLinks: subtopic?.trace_links || [],
                        }
                    );
                    edges.push({ from: topicId, to: subId });
                    attachEvidenceNodes(
                        subId,
                        `role-subtopic:${role}:${topicIndex}:${subIndex}`,
                        {
                            traceLinks: subtopic?.trace_links || [],
                            examples: subtopic?.examples || [],
                        },
                        { color: { background: '#020617', border: communityColor(role) }, level: 5 }
                    );
                });
                if (!Array.isArray(topic?.subtopics) || !topic.subtopics.length) {
                    attachEvidenceNodes(
                        topicId,
                        `role-topic:${role}:${topicIndex}`,
                        { traceLinks: topic?.trace_links || [] },
                        { color: { background: '#0f172a', border: communityColor(role) }, level: 4 }
                    );
                }
            });
        });
    }

    const developerRows = (result?.developers || []).filter((dev) => activeSingles.includes(normalizeRoleLabel(dev?.role)));
    if (mode === 'topics' && selectedTopicSections.has('developer_topics') && developerRows.length) {
        const sectionId = addNode(
            'section:developer-topics',
            formatGraphLabel('Developer Topics', `${developerRows.length} developers`),
            { color: { background: '#111827', border: '#f59e0b' }, fontSize: 17, widthConstraint: { maximum: 240 }, bold: true, level: 1 },
            { type: 'section', title: 'Developer Topics', summary: 'Developer-granular tree grouped by community and contributor.' }
        );
        edges.push({ from: rootId, to: sectionId });

        activeSingles.forEach((role) => {
            const roleDevelopers = developerRows
                .filter((dev) => normalizeRoleLabel(dev?.role) === role)
                .sort((a, b) => Number(b?.documents_count || 0) - Number(a?.documents_count || 0));
            if (!roleDevelopers.length) return;

            const roleId = addNode(
                `developer-role:${role}`,
                formatGraphLabel(communityFilterLabel(role), `${roleDevelopers.length} devs`),
                { color: { background: communityColor(role), border: communityColor(role) }, widthConstraint: { maximum: 180 }, bold: true, level: 2 },
                {
                    type: 'role',
                    title: `${role} Developers`,
                    summary: 'Developer-level topic profiles for this community.',
                    documentsCount: roleDevelopers.reduce((sum, item) => sum + Number(item?.documents_count || 0), 0),
                }
            );
            edges.push({ from: sectionId, to: roleId });
            const developersWithTopics = roleDevelopers.filter((dev) => Array.isArray(dev?.topics) && dev.topics.length > 0);
            if (!developersWithTopics.length) {
                const emptyId = addNode(
                    `developer-role-empty:${role}`,
                    formatGraphLabel(topicExtractionFailureLabel(result, 'No developer topics'), 'No developer-level topics available'),
                    { color: { background: '#111827', border: '#64748b' }, fontSize: 12, widthConstraint: { maximum: 240 }, level: 3 },
                    {
                        type: 'empty',
                        title: `${role} Developer Topics`,
                        role,
                        summary: String(result?.error || 'The analyzer returned no developer topic nodes for this community.'),
                    }
                );
                edges.push({ from: roleId, to: emptyId });
            }

            roleDevelopers.forEach((dev, devIndex) => {
                const developerId = addNode(
                    `developer:${role}:${devIndex}`,
                    formatGraphLabel(shortDeveloperLabel(dev?.developer_id), `${Number(dev?.documents_count || 0)} docs`),
                    { color: { background: '#1f2937', border: communityColor(role) }, widthConstraint: { maximum: 220 }, level: 3 },
                    {
                        type: 'developer',
                        title: String(dev?.developer_id || 'Developer'),
                        role,
                        summary: String(dev?.summary || ''),
                        documentsCount: Number(dev?.documents_count || 0),
                        traceLinks: dev?.trace_links || [],
                    }
                );
                edges.push({ from: roleId, to: developerId });

                const developerTopics = Array.isArray(dev?.topics) ? dev.topics : [];
                if (!developerTopics.length) {
                    const emptyId = addNode(
                        `developer-topic-empty:${role}:${devIndex}`,
                        formatGraphLabel('No topics extracted', 'No developer topics available'),
                        { color: { background: '#0f172a', border: '#475569' }, fontSize: 11, widthConstraint: { maximum: 210 }, level: 4 },
                        {
                            type: 'empty',
                            title: `Topics for ${String(dev?.developer_id || 'developer')}`,
                            role,
                            developerId: String(dev?.developer_id || ''),
                            summary: 'This developer has no extracted topic nodes in the current result.',
                        }
                    );
                    edges.push({ from: developerId, to: emptyId });
                }
                developerTopics.forEach((topic, topicIndex) => {
                    const topicId = addNode(
                        `developer-topic:${role}:${devIndex}:${topicIndex}`,
                        formatGraphLabel(String(topic?.name || 'Topic'), `${topicDisplayEvidenceCount(topic)} evidences`),
                        { color: { background: '#0f172a', border: communityColor(role) }, fontSize: 13, widthConstraint: { maximum: 220 }, level: 4 },
                        {
                            type: 'topic',
                            title: String(topic?.name || 'Topic'),
                            role,
                            developerId: String(dev?.developer_id || ''),
                            summary: String(topic?.summary || ''),
                            evidenceCount: topicDisplayEvidenceCount(topic),
                            traceLinks: topic?.trace_links || [],
                        }
                    );
                    edges.push({ from: developerId, to: topicId });

                    (topic?.subtopics || []).forEach((subtopic, subIndex) => {
                        const subId = addNode(
                            `developer-subtopic:${role}:${devIndex}:${topicIndex}:${subIndex}`,
                            formatGraphLabel(String(subtopic?.name || 'Subtopic'), `${subtopicDisplayEvidenceCount(subtopic)} evidences`),
                            { shape: 'ellipse', color: { background: '#020617', border: communityColor(role) }, fontSize: 12, widthConstraint: { maximum: 210 }, level: 5 },
                            {
                                type: 'subtopic',
                                title: String(subtopic?.name || 'Subtopic'),
                                role,
                                developerId: String(dev?.developer_id || ''),
                                summary: String(subtopic?.summary || ''),
                                evidenceCount: subtopicDisplayEvidenceCount(subtopic),
                                examples: subtopic?.examples || [],
                                traceLinks: subtopic?.trace_links || [],
                            }
                        );
                        edges.push({ from: topicId, to: subId });
                        attachEvidenceNodes(
                            subId,
                            `developer-subtopic:${role}:${devIndex}:${topicIndex}:${subIndex}`,
                            {
                                traceLinks: subtopic?.trace_links || [],
                                examples: subtopic?.examples || [],
                            },
                            { color: { background: '#020617', border: communityColor(role) }, level: 6 }
                        );
                    });
                    if (!Array.isArray(topic?.subtopics) || !topic.subtopics.length) {
                        attachEvidenceNodes(
                            topicId,
                            `developer-topic:${role}:${devIndex}:${topicIndex}`,
                            { traceLinks: topic?.trace_links || [] },
                            { color: { background: '#020617', border: communityColor(role) }, level: 5 }
                        );
                    }
                });
            });
        });
    }

    const includeAllConflictGroups = allConflictFiltersSelected(selectedConflictFilters);
    const conflictRows = (result?.conflicts || []).filter((conflict) => {
        const key = conflictCommunityKey(conflict);
        return includeAllConflictGroups || selectedConflictFilters.has(key);
    });
    const candidateRows = (result?.potential_conflict_threads || []).filter((thread) => {
        const key = potentialConflictCommunityKey(thread);
        return includeAllConflictGroups || selectedConflictFilters.has(key);
    });
    if (mode === 'conflicts' && (conflictRows.length || candidateRows.length)) {
        const sectionId = addNode(
            'section:conflicts',
            formatGraphLabel('Developer Conflicts', `${conflictRows.length + candidateRows.length} records`),
            { color: { background: '#111827', border: '#f87171' }, fontSize: 17, widthConstraint: { maximum: 250 }, bold: true, level: 1 },
            {
                type: 'section',
                title: 'Developer Conflicts',
                summary: 'Conflict branches grouped by community combination. Potential threads are heuristic candidates to inspect when confirmed conflicts are absent.',
                potentialConflictThreads: candidateRows,
            }
        );
        edges.push({ from: rootId, to: sectionId });

        const grouped = new Map();
        conflictRows.forEach((conflict) => {
            const key = conflictCommunityKey(conflict);
            if (!grouped.has(key)) grouped.set(key, []);
            grouped.get(key).push(conflict);
        });

        const comboKeys = Array.from(grouped.keys()).sort((a, b) => {
            const orderA = CONFLICT_FILTER_OPTIONS.findIndex((item) => item.key === a);
            const orderB = CONFLICT_FILTER_OPTIONS.findIndex((item) => item.key === b);
            if (orderA >= 0 && orderB >= 0) return orderA - orderB;
            if (orderA >= 0) return -1;
            if (orderB >= 0) return 1;
            return String(a).localeCompare(String(b));
        });

        comboKeys.forEach((comboKey) => {
            const rows = grouped.get(comboKey) || [];
            if (!rows.length) return;
            const comboId = addNode(
                `conflict-combo:${comboKey}`,
                formatGraphLabel(communityKeyDisplayLabel(comboKey, 'conflict'), `${rows.length} conflicts`),
                { color: { background: communityColor(comboKey), border: communityColor(comboKey) }, widthConstraint: { maximum: 190 }, bold: true, level: 2 },
                {
                    type: 'combination',
                    title: communityKeyDisplayLabel(comboKey, 'conflict'),
                    summary: `${rows.length} evidence-backed conflict records in this community combination.`,
                    count: rows.length,
                }
            );
            edges.push({ from: sectionId, to: comboId });

            rows.forEach((conflict, index) => {
                const conflictTitle = String(conflict?.conflict_title || conflict?.summary || 'Conflict case');
                const participantCount = Array.isArray(conflict?.participant_ids) && conflict.participant_ids.length
                    ? conflict.participant_ids.length
                    : 2;
                const pairId = addNode(
                    `conflict:${comboKey}:${index}`,
                    formatGraphLabel(
                        conflictTitle,
                        `${participantCount} participants | ${String(conflict?.status || 'unknown')}${conflict?.open_conflict ? ' | open' : ''}`
                    ),
                    { color: { background: '#1f2937', border: communityColor(comboKey) }, widthConstraint: { maximum: 270 }, level: 3 },
                    {
                        type: 'conflict',
                        title: conflictTitle,
                        roleCombination: comboKey,
                        developerRole: normalizeRoleLabel(conflict?.developer_role),
                        counterpartRole: normalizeRoleLabel(conflict?.counterpart_role),
                        developerId: String(conflict?.developer_id || ''),
                        counterpartId: String(conflict?.counterpart_id || ''),
                        participantIds: Array.isArray(conflict?.participant_ids) ? conflict.participant_ids : [],
                        participantRoles: Array.isArray(conflict?.participant_roles) ? conflict.participant_roles : [],
                        summary: String(conflict?.summary || ''),
                        resolutionSummary: String(conflict?.resolution_summary || ''),
                        status: String(conflict?.status || 'unknown'),
                        openConflict: Boolean(conflict?.open_conflict),
                        evidenceCount: Number(conflict?.evidence_count || 0),
                        primaryLink: conflict?.primary_link || null,
                        traceLinks: conflict?.source_links || [],
                    }
                );
                edges.push({ from: comboId, to: pairId });
                attachEvidenceNodes(
                    pairId,
                    `conflict:${comboKey}:${index}`,
                    {
                        traceLinks: [
                            ...(conflict?.primary_link ? [conflict.primary_link] : []),
                            ...(Array.isArray(conflict?.source_links) ? conflict.source_links : []),
                        ],
                    },
                    { color: { background: '#1f2937', border: '#fca5a5' }, level: 4 }
                );
            });
        });

        if (candidateRows.length) {
            const candidateSectionId = addNode(
                'section:potential-conflicts',
                formatGraphLabel('Potential Threads', `${candidateRows.length} candidates`),
                { color: { background: '#3f1d1d', border: '#fca5a5' }, fontSize: 16, widthConstraint: { maximum: 240 }, bold: true, level: 2 },
                {
                    type: 'potential_conflicts',
                    title: 'Potential Conflict Threads',
                    summary: `${candidateRows.length} heuristic thread candidates with tension signals and traceability links.`,
                    potentialConflictThreads: candidateRows,
                }
            );
            edges.push({ from: sectionId, to: candidateSectionId });

            candidateRows.forEach((thread, index) => {
                const signalCount = Array.isArray(thread?.matched_signals) ? thread.matched_signals.length : 0;
                const threadId = addNode(
                    `potential-thread:${index}`,
                    formatGraphLabel(String(thread?.thread_label || 'Potential conflict thread'), `${signalCount} signals`),
                    { color: { background: '#1f2937', border: '#fca5a5' }, widthConstraint: { maximum: 270 }, level: 3 },
                    {
                        type: 'potential_conflict_thread',
                        title: String(thread?.thread_label || thread?.thread_id || 'Potential conflict thread'),
                        summary: String(thread?.summary || ''),
                        status: 'potential',
                        openConflict: Boolean(thread?.is_open),
                        matchedSignals: Array.isArray(thread?.matched_signals) ? thread.matched_signals : [],
                        participantIds: Array.isArray(thread?.participant_ids) ? thread.participant_ids : [],
                        traceLinks: Array.isArray(thread?.source_links) ? thread.source_links : [],
                    }
                );
                edges.push({ from: candidateSectionId, to: threadId });
                attachEvidenceNodes(
                    threadId,
                    `potential-thread:${index}`,
                    {
                        traceLinks: Array.isArray(thread?.source_links) ? thread.source_links : [],
                        matchedSignals: Array.isArray(thread?.matched_signals) ? thread.matched_signals : [],
                    },
                    { color: { background: '#1f2937', border: '#fca5a5' }, level: 4 }
                );
            });
        }
    }

    return { nodes, edges, metadata };
}

function topicDetailHtml(meta, result, selectedFilters, selectedSections, options = {}) {
    const compact = Boolean(options?.compact);
    const filterLabelFn = typeof options?.filterLabelFn === 'function' ? options.filterLabelFn : communityFilterLabel;
    const sectionBadges = Array.isArray(options?.sectionBadges)
        ? options.sectionBadges
        : TOPIC_SECTION_OPTIONS
            .filter((item) => (selectedSections || new Set()).has(item.key))
            .map((item) => item.label);
    if (!meta) {
        const notes = Array.isArray(result?.taxonomy_notes) ? result.taxonomy_notes.filter(Boolean) : [];
        return `
            <div class="topic-detail-placeholder${compact ? ' compact' : ''}">
                <h4>Tree Explorer</h4>
                <p>Use the filters above and click a node in the graph to inspect topic summaries, developer evidence, conflicts, resolutions, and traceability links.</p>
                <div class="topic-detail-badges">
                    ${Array.from(selectedFilters || []).map((key) => `<span class="topic-filter-chip active static">${escapeHtml(filterLabelFn(key))}</span>`).join('')}
                </div>
                <div class="topic-detail-badges">
                    ${sectionBadges.map((label) => `<span class="topic-filter-chip active static">${escapeHtml(label)}</span>`).join('')}
                </div>
                ${notes.length ? `<div class="topic-note-list">${notes.map((note) => `<div class="topic-note-item">${escapeHtml(note)}</div>`).join('')}</div>` : ''}
            </div>
        `;
    }

    const metaRows = [];
    if (meta.role) metaRows.push(meta.role);
    if (meta.developerId) metaRows.push(`developer: ${meta.developerId}`);
    if (meta.documentsCount > 0) metaRows.push(`${meta.documentsCount} docs`);
    if (meta.evidenceCount > 0) metaRows.push(`${meta.evidenceCount} evidences`);
    if (meta.status) metaRows.push(`status: ${meta.status}`);
    if (meta.openConflict) metaRows.push('open thread detected');
    if (meta.roleCombination) metaRows.push(meta.roleCombination);
    if (Array.isArray(meta.participantRoles) && meta.participantRoles.length) metaRows.push(`roles: ${meta.participantRoles.join(', ')}`);
    if (meta.model) metaRows.push(`model: ${meta.model}`);
    if (meta.judgeModel) metaRows.push(`judge: ${meta.judgeModel}`);
    if (meta.sourceCount > 0) metaRows.push(`${meta.sourceCount} sources`);
    if (meta.discussionSourceCount > 0) metaRows.push(`${meta.discussionSourceCount} discussion sources`);
    if (meta.llmRunCount > 0) metaRows.push(`${meta.llmRunCount} run(s)`);
    if (meta.judged) metaRows.push('LLM judge enabled');
    const hasBody = Boolean(
        meta.summary ||
        meta.resolutionSummary ||
        meta.primaryLink ||
        (Array.isArray(meta.examples) && meta.examples.length) ||
        (Array.isArray(meta.traceLinks) && meta.traceLinks.length) ||
        (Array.isArray(meta.taxonomyNotes) && meta.taxonomyNotes.length) ||
        meta.sourceBreakdownText ||
        (Array.isArray(meta.matchedSignals) && meta.matchedSignals.length) ||
        (Array.isArray(meta.participantIds) && meta.participantIds.length) ||
        (Array.isArray(meta.potentialConflictThreads) && meta.potentialConflictThreads.length)
    );

    return `
        <div class="topic-detail-card${compact ? ' compact' : ''}">
            <h4>${escapeHtml(meta.title || 'Details')}</h4>
            ${metaRows.length ? `<div class="topic-detail-meta">${metaRows.map((row) => `<span>${escapeHtml(row)}</span>`).join('')}</div>` : ''}
            ${meta.summary ? `<div class="topic-node-summary">${escapeHtml(meta.summary)}</div>` : ''}
            ${meta.sourceBreakdownText ? `<div class="topic-node-summary"><b>Source mix:</b> ${escapeHtml(meta.sourceBreakdownText)}</div>` : ''}
            ${Array.isArray(meta.matchedSignals) && meta.matchedSignals.length ? `<div class="topic-node-summary"><b>Signals:</b> ${escapeHtml(meta.matchedSignals.join(', '))}</div>` : ''}
            ${Array.isArray(meta.participantIds) && meta.participantIds.length ? `<div class="topic-node-summary"><b>Participants:</b> ${escapeHtml(meta.participantIds.join(', '))}</div>` : ''}
            ${(meta.developerId || meta.counterpartId) ? `<div class="topic-node-summary"><b>Primary opposition:</b> ${escapeHtml([meta.developerId, meta.counterpartId].filter(Boolean).join(' <> '))}</div>` : ''}
            ${renderPrimaryTraceLink(meta.primaryLink)}
            ${meta.resolutionSummary ? `<div class="topic-detail-resolution"><b>Resolution:</b> ${escapeHtml(meta.resolutionSummary)}</div>` : ''}
            ${Array.isArray(meta.examples) && meta.examples.length ? `<div class="topic-example-list">${meta.examples.map((example) => `<div>${escapeHtml(example)}</div>`).join('')}</div>` : ''}
            ${renderTraceLinks(meta.traceLinks || [], 'No traceability links for this node.')}
            ${renderPotentialConflictThreads(meta.potentialConflictThreads || [])}
            ${Array.isArray(meta.taxonomyNotes) && meta.taxonomyNotes.length ? `<div class="topic-note-list">${meta.taxonomyNotes.map((note) => `<div class="topic-note-item">${escapeHtml(note)}</div>`).join('')}</div>` : ''}
            ${!hasBody ? '<div class="topic-links-empty">No extra summary is available for this node yet.</div>' : ''}
        </div>
    `;
}

function renderTopicDetailPanel(detailEl, meta, result, selectedFilters, selectedSections, options = {}) {
    if (!detailEl) return;
    detailEl.innerHTML = topicDetailHtml(meta, result, selectedFilters, selectedSections, options);
}

function treeButton(id, label, extraClass = '') {
    return `<button type="button" class="topic-tree-node-btn ${extraClass}" data-topic-node-id="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
}

function treeBranch(buttonHtml, childrenHtml = '', detailHtml = '') {
    return `
        <li class="topic-tree-item">
            <div class="topic-tree-node-wrap">${buttonHtml}</div>
            ${detailHtml || ''}
            ${childrenHtml ? `<div class="topic-tree-children-wrap"><ul class="topic-tree-children">${childrenHtml}</ul></div>` : ''}
        </li>
    `;
}

function buildTopicHierarchyOptions() {
    return {
        autoResize: true,
        physics: false,
        layout: {
            hierarchical: {
                enabled: true,
                direction: 'UD',
                sortMethod: 'directed',
                shakeTowards: 'roots',
                levelSeparation: 180,
                nodeSpacing: 220,
                treeSpacing: 280,
                blockShifting: true,
                edgeMinimization: true,
                parentCentralization: true,
            }
        },
        nodes: {
            shape: 'box',
            margin: 12,
            borderWidth: 1.5,
            borderWidthSelected: 2.5,
            font: { color: '#f8fafc', face: 'Outfit', size: 15 },
        },
        edges: {
            color: { color: 'rgba(56, 189, 248, 0.26)', highlight: 'rgba(56, 189, 248, 0.9)' },
            width: 1.4,
            selectionWidth: 2.4,
            smooth: {
                enabled: true,
                type: 'cubicBezier',
                forceDirection: 'vertical',
                roundness: 0.42,
            }
        },
        interaction: {
            hover: true,
            dragView: true,
            dragNodes: false,
            zoomView: true,
            navigationButtons: true,
            keyboard: true,
            tooltipDelay: 100,
        }
    };
}

function renderTopicExplorerPanel(panelEl, result, options = {}) {
    if (!panelEl) return;
    const scopeKey = String(options.scopeKey || 'scope');
    const mode = String(options.mode || 'topics');
    const panelKey = `${scopeKey}:${mode}`;
    panelEl.innerHTML = `
        <div class="topic-explorer-section ${mode === 'conflicts' ? 'conflict' : 'topics'}">
            <div class="topic-explorer-section-header">
                <div>
                    <h4>${escapeHtml(options.title || (mode === 'conflicts' ? 'Conflicts Explorer' : 'Topics Explorer'))}</h4>
                    <p>${escapeHtml(options.subtitle || '')}</p>
                </div>
            </div>
            <div class="topic-graph-shell">
                <div id="topicGraphDetail_${panelKey.replace(/[^a-zA-Z0-9_-]+/g, '_')}" class="topic-graph-detail topic-graph-detail-top"></div>
                <div class="topic-graph-layout">
                    <div id="topicGraphCanvas_${panelKey.replace(/[^a-zA-Z0-9_-]+/g, '_')}" class="topic-graph-canvas ${mode === 'conflicts' ? 'topic-graph-canvas-conflicts' : ''}"></div>
                </div>
            </div>
        </div>
    `;

    const oldGraph = topicGraphInstances.get(panelKey);
    if (oldGraph) {
        oldGraph.destroy();
        topicGraphInstances.delete(panelKey);
    }

    const graphEl = document.getElementById(`topicGraphCanvas_${panelKey.replace(/[^a-zA-Z0-9_-]+/g, '_')}`);
    const detailEl = document.getElementById(`topicGraphDetail_${panelKey.replace(/[^a-zA-Z0-9_-]+/g, '_')}`);
    const graphData = buildTopicExplorerGraph(result, {
        scopeKey: panelKey,
        mode,
        selectedRoleFilters: options.selectedRoleFilters,
        selectedConflictFilters: options.selectedConflictFilters,
        selectedTopicSections: options.selectedTopicSections,
    });
    const metadata = graphData.metadata || {};
    const rootNode = Array.isArray(graphData.nodes) ? graphData.nodes[0] : null;
    const rootNodeId = rootNode?.id || '';
    const rootMeta = metadata[rootNodeId] || {
        type: 'root',
        title: mode === 'conflicts' ? 'Conflict Explorer' : 'Topics Explorer',
        summary: mode === 'conflicts'
            ? 'Inspect confirmed conflicts and potential tension threads.'
            : 'Inspect role and developer topics with empirical traceability.',
    };
    const selectedNodeIds = options.selectedNodeIds || {};
    const selectedNodeId = metadata[selectedNodeIds[mode]] ? selectedNodeIds[mode] : rootNodeId;
    selectedNodeIds[mode] = selectedNodeId || '';

    if (!Array.isArray(graphData.nodes) || !graphData.nodes.length || graphData.nodes.length === 1) {
        graphEl.innerHTML = `<div class="topic-empty">${escapeHtml(options.emptyMessage || 'No content available for the selected filters.')}</div>`;
        renderTopicDetailPanel(detailEl, rootMeta, result, options.badgeFilters || new Set(), options.badgeSections || new Set(), options.detailOptions || {});
        return;
    }

    const data = {
        nodes: new vis.DataSet(graphData.nodes),
        edges: new vis.DataSet(graphData.edges),
    };
    const network = new vis.Network(graphEl, data, buildTopicHierarchyOptions());
    topicGraphInstances.set(panelKey, network);

    renderTopicDetailPanel(detailEl, metadata[selectedNodeIds[mode]] || rootMeta, result, options.badgeFilters || new Set(), options.badgeSections || new Set(), options.detailOptions || {});

    network.once('stabilizationIterationsDone', () => {
        network.setOptions({ physics: false });
        network.fit({ animation: { duration: 280, easingFunction: 'easeInOutQuad' } });
        if (selectedNodeIds[mode]) {
            network.selectNodes([selectedNodeIds[mode]]);
        }
    });

    network.on('click', (params) => {
        if (!params.nodes || !params.nodes.length) return;
        selectedNodeIds[mode] = params.nodes[0];
        network.focus(selectedNodeIds[mode], {
            scale: 0.95,
            animation: { duration: 220, easingFunction: 'easeInOutQuad' },
        });
        renderTopicDetailPanel(detailEl, metadata[selectedNodeIds[mode]] || rootMeta, result, options.badgeFilters || new Set(), options.badgeSections || new Set(), options.detailOptions || {});
    });
}

function renderTopicTree(container, result, scopeKey = 'global') {
    if (!container) return;
    const roles = Array.isArray(result?.roles) ? result.roles : [];
    const developers = Array.isArray(result?.developers) ? result.developers : [];
    const conflicts = Array.isArray(result?.conflicts) ? result.conflicts : [];
    const potentialConflicts = Array.isArray(result?.potential_conflict_threads) ? result.potential_conflict_threads : [];
    if (!roles.length && !developers.length && !conflicts.length && !potentialConflicts.length) {
        const oldGraph = topicGraphInstances.get(scopeKey);
        if (oldGraph) {
            oldGraph.destroy();
            topicGraphInstances.delete(scopeKey);
        }
        container.innerHTML = '<div style="color:#94a3b8; font-size:0.84rem;">No topic tree available yet.</div>';
        return;
    }

    const state = getTopicExplorerState(scopeKey);
    const { availableRoles, availableConflicts } = extractAvailableTopicFilterKeys(result);
    if (!(state.selectedRoleFilters instanceof Set)) {
        state.selectedRoleFilters = new Set();
    }
    if (!(state.selectedConflictFilters instanceof Set)) {
        state.selectedConflictFilters = new Set();
    }
    if (!(state.selectedTopicSections instanceof Set)) {
        state.selectedTopicSections = new Set();
    }

    const showTopicsPanel = state.selectedRoleFilters.size > 0 && state.selectedTopicSections.size > 0;
    const showConflictsPanel = state.selectedConflictFilters.size > 0;
    const topicsPanelKey = `${scopeKey}:topics`;
    const conflictsPanelKey = `${scopeKey}:conflicts`;
    if (!showTopicsPanel) {
        const staleTopicsGraph = topicGraphInstances.get(topicsPanelKey);
        if (staleTopicsGraph) {
            staleTopicsGraph.destroy();
            topicGraphInstances.delete(topicsPanelKey);
        }
    }
    if (!showConflictsPanel) {
        const staleConflictsGraph = topicGraphInstances.get(conflictsPanelKey);
        if (staleConflictsGraph) {
            staleConflictsGraph.destroy();
            topicGraphInstances.delete(conflictsPanelKey);
        }
    }

    const shellId = String(scopeKey || 'graph').replace(/[^a-zA-Z0-9_-]+/g, '_');
    container.innerHTML = `
        <div class="topic-explorer-layout">
            <div class="topic-filter-card-grid">
                <div class="topic-filter-card">
                    <div class="topic-filter-card-header">
                        <div>
                            <h4>Topics</h4>
                            <p>Choose which communities and topic layers to show.</p>
                        </div>
                        <div class="topic-filter-card-actions">
                            <button type="button" class="topic-filter-action" data-topic-role-select-all="1">Select all</button>
                            <button type="button" class="topic-filter-action" data-topic-role-clear="1">Clear</button>
                        </div>
                    </div>
                    <div class="topic-filter-group">
                        <div class="topic-filter-toolbar-label">Community filters</div>
                        <div class="topic-filter-toolbar">
                            ${ROLE_FILTER_OPTIONS.map((item) => `
                                <button
                                    type="button"
                                    class="topic-filter-chip ${state.selectedRoleFilters.has(item.key) ? 'active' : ''} ${availableRoles.has(item.key) ? '' : 'muted'}"
                                    data-topic-role-filter="${escapeHtml(item.key)}"
                                >${escapeHtml(item.label)}</button>
                            `).join('')}
                        </div>
                    </div>
                    <div class="topic-filter-group">
                        <div class="topic-filter-toolbar-label">Content shown</div>
                        <div class="topic-filter-toolbar">
                            ${TOPIC_SECTION_OPTIONS.map((item) => `
                                <button
                                    type="button"
                                    class="topic-filter-chip topic-section-chip ${state.selectedTopicSections.has(item.key) ? 'active' : ''}"
                                    data-topic-section="${escapeHtml(item.key)}"
                                >${escapeHtml(item.label)}</button>
                            `).join('')}
                        </div>
                    </div>
                </div>
                <div class="topic-filter-card conflict-card">
                    <div class="topic-filter-card-header">
                        <div>
                            <h4>Conflicts</h4>
                            <p>Filter the conflict explorer by community combination.</p>
                        </div>
                        <div class="topic-filter-card-actions">
                            <button type="button" class="topic-filter-action danger" data-topic-conflict-select-all="1">Select all</button>
                            <button type="button" class="topic-filter-action danger" data-topic-conflict-clear="1">Clear</button>
                        </div>
                    </div>
                    <div class="topic-filter-group">
                        <div class="topic-filter-toolbar-label">Community combinations</div>
                        <div class="topic-filter-toolbar">
                            ${CONFLICT_FILTER_OPTIONS.map((item) => `
                                <button
                                    type="button"
                                    class="topic-filter-chip topic-combo-chip ${state.selectedConflictFilters.has(item.key) ? 'active' : ''} ${availableConflicts.has(item.key) ? '' : 'muted'}"
                                    data-topic-conflict-filter="${escapeHtml(item.key)}"
                                >${escapeHtml(item.label)}</button>
                            `).join('')}
                        </div>
                    </div>
                </div>
            </div>
            ${showTopicsPanel ? `<div id="topicExplorerTopics_${shellId}"></div>` : ''}
            ${showConflictsPanel ? `<div id="topicExplorerConflicts_${shellId}"></div>` : ''}
            ${!showTopicsPanel && !showConflictsPanel ? '<div class="topic-empty">Enable at least one Topic or Conflict filter to render the graph panels.</div>' : ''}
        </div>
    `;

    if (showTopicsPanel) {
        renderTopicExplorerPanel(document.getElementById(`topicExplorerTopics_${shellId}`), result, {
            scopeKey,
            mode: 'topics',
            title: 'Topics Explorer',
            subtitle: 'Role topics and developer topics stay together here, separate from the conflict analysis.',
            emptyMessage: 'No topic content available for the selected filters.',
            selectedRoleFilters: state.selectedRoleFilters,
            selectedConflictFilters: state.selectedConflictFilters,
            selectedTopicSections: state.selectedTopicSections,
            selectedNodeIds: state.selectedNodeIds,
            badgeFilters: state.selectedRoleFilters,
            badgeSections: state.selectedTopicSections,
            detailOptions: {
                filterLabelFn: communityFilterLabel,
            },
        });
    }
    if (showConflictsPanel) {
        renderTopicExplorerPanel(document.getElementById(`topicExplorerConflicts_${shellId}`), result, {
            scopeKey,
            mode: 'conflicts',
            title: 'Conflicts Explorer',
            subtitle: 'Confirmed conflicts and potential tension threads are isolated here for easier reading.',
            emptyMessage: 'No conflict content available for the selected community combinations.',
            selectedRoleFilters: state.selectedRoleFilters,
            selectedConflictFilters: state.selectedConflictFilters,
            selectedTopicSections: state.selectedTopicSections,
            selectedNodeIds: state.selectedNodeIds,
            badgeFilters: state.selectedConflictFilters,
            badgeSections: new Set(['conflicts']),
            detailOptions: {
                filterLabelFn: conflictFilterLabel,
                sectionBadges: ['Conflicts'],
            },
        });
    }

    container.querySelectorAll('[data-topic-role-filter]').forEach((button) => {
        button.addEventListener('click', () => {
            const key = button.getAttribute('data-topic-role-filter') || '';
            if (state.selectedRoleFilters.has(key)) {
                state.selectedRoleFilters.delete(key);
            } else {
                state.selectedRoleFilters.add(key);
            }
            renderTopicTree(container, result, scopeKey);
        });
    });

    container.querySelectorAll('[data-topic-conflict-filter]').forEach((button) => {
        button.addEventListener('click', () => {
            const key = button.getAttribute('data-topic-conflict-filter') || '';
            if (state.selectedConflictFilters.has(key)) {
                state.selectedConflictFilters.delete(key);
            } else {
                state.selectedConflictFilters.add(key);
            }
            renderTopicTree(container, result, scopeKey);
        });
    });

    container.querySelectorAll('[data-topic-section]').forEach((button) => {
        button.addEventListener('click', () => {
            const key = button.getAttribute('data-topic-section') || '';
            if (state.selectedTopicSections.has(key)) {
                state.selectedTopicSections.delete(key);
            } else {
                state.selectedTopicSections.add(key);
            }
            renderTopicTree(container, result, scopeKey);
        });
    });

    const roleSelectAllBtn = container.querySelector('[data-topic-role-select-all="1"]');
    if (roleSelectAllBtn) {
        roleSelectAllBtn.addEventListener('click', () => {
            state.selectedRoleFilters = new Set(ROLE_FILTER_OPTIONS.map((item) => item.key));
            renderTopicTree(container, result, scopeKey);
        });
    }

    const roleClearBtn = container.querySelector('[data-topic-role-clear="1"]');
    if (roleClearBtn) {
        roleClearBtn.addEventListener('click', () => {
            state.selectedRoleFilters = new Set();
            renderTopicTree(container, result, scopeKey);
        });
    }

    const conflictSelectAllBtn = container.querySelector('[data-topic-conflict-select-all="1"]');
    if (conflictSelectAllBtn) {
        conflictSelectAllBtn.addEventListener('click', () => {
            state.selectedConflictFilters = new Set(CONFLICT_FILTER_OPTIONS.map((item) => item.key));
            renderTopicTree(container, result, scopeKey);
        });
    }

    const conflictClearBtn = container.querySelector('[data-topic-conflict-clear="1"]');
    if (conflictClearBtn) {
        conflictClearBtn.addEventListener('click', () => {
            state.selectedConflictFilters = new Set();
            renderTopicTree(container, result, scopeKey);
        });
    }
}

function renderTopicStatus(container, result, fallbackMessage) {
    if (!container) return;
    const status = String(result?.status || fallbackMessage || 'Not analyzed');
    const model = String(result?.model || '').trim();
    const sourceCount = Number(result?.source_count || 0);
    const generatedAt = formatTopicTimestamp(result?.generated_at);
    const error = String(result?.error || '').trim();

    const parts = [status];
    if (model) parts.push(`model: ${model}`);
    if (Number(result?.llm_run_count || 0) > 0) parts.push(`runs: ${Number(result?.llm_run_count || 1)}`);
    if (result?.judged) parts.push(`judge: ${String(result?.judge_model || model || 'enabled')}`);
    if (sourceCount > 0) parts.push(`documents: ${sourceCount}`);
    if (Number(result?.discussion_source_count || 0) > 0) {
        parts.push(`discussion sources: ${Number(result?.discussion_source_count || 0)}`);
    }
    if (Array.isArray(result?.potential_conflict_threads) && result.potential_conflict_threads.length) {
        parts.push(`potential conflict threads: ${result.potential_conflict_threads.length}`);
    }
    if (generatedAt) parts.push(`generated: ${generatedAt}`);
    if (error) parts.push(`error: ${error}`);
    container.innerHTML = parts.map((x) => escapeHtml(x)).join(' | ');
}

function renderProjectTopics(project) {
    const result = project?.topic_modeling || null;
    renderTopicStatus(projectTopicsStatus, result, 'Not analyzed');
    renderTopicTree(projectTopicsTree, result, `project_${project?.id || 'current'}`);
}

async function refreshGlobalTopics() {
    if (!globalTopicsStatus || !globalTopicsTree) return;
    try {
        const res = await fetch(`${API_URL}/topics/overall`);
        const body = await res.json();
        renderTopicStatus(globalTopicsStatus, body, 'Not analyzed');
        renderTopicTree(globalTopicsTree, body, 'global_topics');
    } catch (err) {
        console.error('Failed to fetch overall topics', err);
        globalTopicsStatus.innerHTML = 'Unable to reach backend for overall topics.';
        globalTopicsTree.innerHTML = '';
    }
}

async function loadLlmSettings() {
    if (!llmSettingsStatus) return;
    try {
        const res = await fetch(`${API_URL}/settings/llm`);
        const body = await res.json();
        if (!res.ok) {
            llmSettingsStatus.innerHTML = escapeHtml(body?.detail || 'Failed to load LLM settings.');
            return;
        }

        if (llmModelInput) llmModelInput.value = body?.model || 'gpt-5-mini';
        if (llmRunsInput) llmRunsInput.value = String(Math.max(1, Number(body?.llm_runs || 1)));
        if (llmOrganizationInput) llmOrganizationInput.value = body?.organization || '';
        if (llmProjectInput) llmProjectInput.value = body?.project || '';
        if (llmEndpointInput) llmEndpointInput.value = body?.endpoint || 'https://api.openai.com/v1/chat/completions';
        if (llmApiKeyInput) llmApiKeyInput.value = '';
        if (githubTokenInput) githubTokenInput.value = '';
        if (llmApiKeyHint) {
            llmApiKeyHint.innerText = body?.has_api_key
                ? `Saved key detected: ${body?.api_key_masked || 'configured'}`
                : 'No key saved yet.';
        }
        if (githubTokenHint) {
            githubTokenHint.innerText = body?.has_github_token
                ? `Saved token detected: ${body?.github_token_masked || 'configured'}`
                : 'No GitHub token saved yet.';
        }

        if (body?.has_api_key && body?.has_github_token) {
            llmSettingsStatus.innerHTML = `LLM and GitHub settings ready | model: ${escapeHtml(body?.model || 'gpt-5-mini')} | runs: ${Math.max(1, Number(body?.llm_runs || 1))}`;
        } else if (body?.has_api_key) {
            llmSettingsStatus.innerHTML = `LLM settings ready | model: ${escapeHtml(body?.model || 'gpt-5-mini')} | runs: ${Math.max(1, Number(body?.llm_runs || 1))} | GitHub token missing`;
        } else {
            llmSettingsStatus.innerHTML = 'Set your OpenAI API key and model to enable topic extraction.';
        }
    } catch (err) {
        console.error('Failed to load LLM settings', err);
        llmSettingsStatus.innerHTML = 'Unable to reach backend for LLM settings.';
    }
}

function shortenText(text, maxLen = 140) {
    const s = String(text || '').trim();
    if (!s) return '';
    if (s.length <= maxLen) return s;
    return `${s.slice(0, maxLen - 1)}…`;
}

function buildOverallDeveloperSummaries(windows) {
    const byId = new Map();
    const lastWindowIdx = Math.max(0, (windows || []).length - 1);

    (windows || []).forEach((w, windowIdx) => {
        (w.developers || []).forEach((d) => {
            const id = String(d.id || '').trim();
            if (!id) return;

            let row = byId.get(id);
            if (!row) {
                row = {
                    id,
                    aliases: new Set(),
                    emails: new Set(),
                    classification: 'Unknown',
                    gender: 'Unknown',
                    sentimentWeighted: 0,
                    sentimentWeight: 0,
                    sentimentMessages: 0,
                    commits: 0,
                    bugFix: 0,
                    bugIntro: 0,
                    filesTouched: 0,
                    churn: 0,
                    communitySmells: new Set(),
                    mlSmells: new Set(),
                    traditionalSmells: new Set(),
                    vulnerabilities: new Set(),
                    mlInstances: 0,
                    traditionalInstances: 0,
                    vulnerabilityInstances: 0,
                    lastSeenWindowIdx: -1,
                    lastSeenWindowLabel: '',
                    lastSeenWindowId: '',
                    abandoned: false,
                    abandonedSinceWindowLabel: '',
                    abandonedSinceDate: null,
                    lastCommitDate: null,
                    lastCommitMessage: '',
                    lastMessageBeforeAbandonmentDate: null,
                    lastMessageBeforeAbandonment: '',
                };
                byId.set(id, row);
            }

            (d.aliases || []).forEach((x) => row.aliases.add(String(x)));
            (d.emails || []).forEach((x) => row.emails.add(String(x)));

            if (d.classification && d.classification !== 'Unknown') row.classification = d.classification;
            if (d.gender && d.gender !== 'Unknown') row.gender = d.gender;

            const msgCount = Math.max(1, safeNum(d.sentiment_messages_count));
            row.sentimentWeighted += safeNum(d.sentiment_score) * msgCount;
            row.sentimentWeight += msgCount;
            row.sentimentMessages += safeNum(d.sentiment_messages_count);

            row.commits += safeNum(d.commits_count);
            row.bugFix += safeNum(d.bug_fix_commits_count);
            row.bugIntro += safeNum(d.bug_introduced_count);
            row.filesTouched += safeNum(d.files_touched_count);
            row.churn += safeNum(d.code_churn);

            (d.community_smells || []).forEach((x) => row.communitySmells.add(String(x)));
            (d.ml_smells || []).forEach((x) => row.mlSmells.add(String(x)));
            (d.traditional_smells || []).forEach((x) => row.traditionalSmells.add(String(x)));
            (d.vulnerabilities || []).forEach((x) => row.vulnerabilities.add(String(x)));
            row.mlInstances += (d.ml_smell_details || []).length;
            row.traditionalInstances += (d.traditional_smell_details || []).length;
            row.vulnerabilityInstances += (d.vulnerability_details || []).length;

            if (windowIdx >= row.lastSeenWindowIdx) {
                row.lastSeenWindowIdx = windowIdx;
                row.lastSeenWindowLabel = String(w.label || d.last_interaction_window_label || '');
                row.lastSeenWindowId = String(w.id || d.last_interaction_window_id || '');
            }

            const commitDt = parseDateValue(d.last_commit_date);
            if (commitDt && (!row.lastCommitDate || commitDt > row.lastCommitDate)) {
                row.lastCommitDate = commitDt;
                row.lastCommitMessage = String(d.last_commit_message || '');
            }

            const beforeAbandonDt = parseDateValue(d.last_message_before_abandonment_date);
            if (beforeAbandonDt && (!row.lastMessageBeforeAbandonmentDate || beforeAbandonDt > row.lastMessageBeforeAbandonmentDate)) {
                row.lastMessageBeforeAbandonmentDate = beforeAbandonDt;
                row.lastMessageBeforeAbandonment = String(d.last_message_before_abandonment || '');
            }

            if (d.is_abandoned) {
                row.abandoned = true;
                row.abandonedSinceWindowLabel = String(d.abandoned_since_window_label || row.abandonedSinceWindowLabel || '');
                const abandonDt = parseDateValue(d.abandoned_since_date);
                if (abandonDt && (!row.abandonedSinceDate || abandonDt < row.abandonedSinceDate)) {
                    row.abandonedSinceDate = abandonDt;
                }
            }
        });
    });

    return Array.from(byId.values()).map((row) => {
        let abandoned = row.abandoned;
        let abandonedSinceLabel = row.abandonedSinceWindowLabel;
        let abandonedSinceDate = row.abandonedSinceDate;

        if (!abandoned && row.lastSeenWindowIdx >= 0 && row.lastSeenWindowIdx < lastWindowIdx) {
            abandoned = true;
            const nextWindow = windows[row.lastSeenWindowIdx + 1];
            if (nextWindow) {
                abandonedSinceLabel = String(nextWindow.label || '');
                abandonedSinceDate = parseDateValue(nextWindow.start_date);
            }
        }

        const avgSentiment = row.sentimentWeight > 0 ? (row.sentimentWeighted / row.sentimentWeight) : 0;
        const beforeMsg = row.lastMessageBeforeAbandonment || (abandoned ? row.lastCommitMessage : '');
        const beforeDate = row.lastMessageBeforeAbandonmentDate || (abandoned ? row.lastCommitDate : null);

        return {
            id: row.id,
            aliases: Array.from(row.aliases).filter(Boolean),
            emails: Array.from(row.emails).filter(Boolean),
            classification: row.classification || 'Unknown',
            gender: row.gender || 'Unknown',
            avgSentiment,
            sentimentMessages: row.sentimentMessages,
            commits: row.commits,
            bugFix: row.bugFix,
            bugIntro: row.bugIntro,
            filesTouched: row.filesTouched,
            churn: row.churn,
            communitySmells: Array.from(row.communitySmells),
            mlSmells: Array.from(row.mlSmells),
            traditionalSmells: Array.from(row.traditionalSmells),
            vulnerabilities: Array.from(row.vulnerabilities),
            mlInstances: row.mlInstances,
            traditionalInstances: row.traditionalInstances,
            vulnerabilityInstances: row.vulnerabilityInstances,
            abandoned,
            abandonedSinceLabel: abandonedSinceLabel || '',
            abandonedSinceDate,
            lastSeenWindowLabel: row.lastSeenWindowLabel,
            lastCommitDate: row.lastCommitDate,
            lastCommitMessage: row.lastCommitMessage,
            lastMessageBeforeAbandonmentDate: beforeDate,
            lastMessageBeforeAbandonment: beforeMsg,
        };
    }).sort((a, b) => {
        if (a.abandoned !== b.abandoned) return a.abandoned ? -1 : 1;
        if (b.commits !== a.commits) return b.commits - a.commits;
        return String(a.id).localeCompare(String(b.id));
    });
}

function renderOverallDevelopersSummary(windows) {
    if (!overallDevelopersSummaryTable) return;

    const rows = buildOverallDeveloperSummaries(windows || []);
    if (!rows.length) {
        overallDevelopersSummaryTable.innerHTML = '<tr><td style="padding:0.6rem; color:#94a3b8;">No developer data available yet.</td></tr>';
        return;
    }

    const head = `
        <thead>
            <tr>
                <th>Developer</th>
                <th>Status</th>
                <th>Abandoned Since</th>
                <th>Last Interaction</th>
                <th>Last Message Before Abandonment</th>
                <th>Last Commit Message</th>
                <th>Classification</th>
                <th>Sentiment</th>
                <th>Commits</th>
                <th>Bug Intro</th>
                <th>Bug Fix</th>
                <th>Files</th>
                <th>Churn</th>
                <th>Community Smells</th>
                <th>ML Smells</th>
                <th>Traditional Smells</th>
                <th>Vulnerabilities</th>
            </tr>
        </thead>
    `;

    const body = rows.map((row) => {
        const status = row.abandoned ? 'Abandoned' : 'Active';
        const abandonedSince = row.abandoned
            ? `${row.abandonedSinceLabel || 'n/a'}${row.abandonedSinceDate ? ` (${formatDateTime(row.abandonedSinceDate)})` : ''}`
            : '-';
        const lastInteraction = row.lastSeenWindowLabel || '-';
        const beforeMsg = row.lastMessageBeforeAbandonment
            ? `${formatDateTime(row.lastMessageBeforeAbandonmentDate) || ''} ${shortenText(row.lastMessageBeforeAbandonment)}`
            : '-';
        const lastCommitMsg = row.lastCommitMessage
            ? `${formatDateTime(row.lastCommitDate) || ''} ${shortenText(row.lastCommitMessage)}`
            : '-';
        const devInfo = `
            <b>${escapeHtml(row.id)}</b>
            <div style="color:#94a3b8; font-size:0.72rem; margin-top:3px;">${escapeHtml(row.gender || 'Unknown')}</div>
            <div style="color:#94a3b8; font-size:0.72rem; margin-top:3px;">${escapeHtml((row.aliases || []).slice(0, 3).join(' | ') || '-')}</div>
        `;
        const comm = `${row.communitySmells.length} (${escapeHtml(row.communitySmells.join(', ') || '-')})`;
        const ml = `${row.mlInstances} inst / ${row.mlSmells.length} types (${escapeHtml(row.mlSmells.join(', ') || '-')})`;
        const trad = `${row.traditionalInstances} inst / ${row.traditionalSmells.length} types (${escapeHtml(row.traditionalSmells.join(', ') || '-')})`;
        const vuln = `${row.vulnerabilityInstances} inst / ${row.vulnerabilities.length} types (${escapeHtml(row.vulnerabilities.join(', ') || '-')})`;

        return `
            <tr>
                <td>${devInfo}</td>
                <td>${status}</td>
                <td>${escapeHtml(abandonedSince)}</td>
                <td>${escapeHtml(lastInteraction)}</td>
                <td class="overall-dev-msg">${escapeHtml(beforeMsg)}</td>
                <td class="overall-dev-msg">${escapeHtml(lastCommitMsg)}</td>
                <td>${escapeHtml(row.classification)}</td>
                <td>${row.avgSentiment.toFixed(3)} (${row.sentimentMessages} msg)</td>
                <td>${row.commits}</td>
                <td>${row.bugIntro}</td>
                <td>${row.bugFix}</td>
                <td>${row.filesTouched}</td>
                <td>${row.churn}</td>
                <td>${comm}</td>
                <td>${ml}</td>
                <td>${trad}</td>
                <td>${vuln}</td>
            </tr>
        `;
    }).join('');

    overallDevelopersSummaryTable.innerHTML = `${head}<tbody>${body}</tbody>`;
}

function renderProjectRoleEvolution(project) {
    const interval = projectRoleIntervalSelect?.value || 'quarterly';
    const result = renderRoleEvolutionCharts({
        projects: project ? [project] : [],
        interval,
        scope: 'project',
        distributionCanvasId: 'projectRoleDistributionChart',
        turnoverCanvasId: 'projectRoleTurnoverChart',
        distributionChart: projectRoleDistributionChart,
        turnoverChart: projectRoleTurnoverChart,
        tableEl: projectRoleTurnoverTable,
    });
    projectRoleDistributionChart = result.distributionChart;
    projectRoleTurnoverChart = result.turnoverChart;
}

function renderGlobalRoleEvolution(projects) {
    const analyzedProjects = (projects || []).filter((project) => Array.isArray(project?.time_windows) && project.time_windows.length > 0);
    const interval = globalRoleIntervalSelect?.value || 'quarterly';
    const result = renderRoleEvolutionCharts({
        projects: analyzedProjects,
        interval,
        scope: 'global',
        distributionCanvasId: 'globalRoleDistributionChart',
        turnoverCanvasId: 'globalRoleTurnoverChart',
        distributionChart: globalRoleDistributionChart,
        turnoverChart: globalRoleTurnoverChart,
        tableEl: globalRoleTurnoverTable,
    });
    globalRoleDistributionChart = result.distributionChart;
    globalRoleTurnoverChart = result.turnoverChart;
}

function renderOverallStats(project) {
    const windows = collectOverallWindows(project);
    if (!overallMetricSelect || !overallMetricsTimelineTable) return;
    renderOverallNetwork(project);
    renderProjectRoleEvolution(project);
    renderProjectTopics(project);

    if (!windows.length) {
        overallMetricSelect.innerHTML = '<option value="">No metrics available</option>';
        overallMetricsTimelineTable.innerHTML = '<tr><td style="padding:0.6rem; color:#94a3b8;">No time-window metrics available yet.</td></tr>';
        if (overallDevelopersSummaryTable) {
            overallDevelopersSummaryTable.innerHTML = '<tr><td style="padding:0.6rem; color:#94a3b8;">No developer data available yet.</td></tr>';
        }
        if (overallMetricTrendChart) {
            overallMetricTrendChart.destroy();
            overallMetricTrendChart = null;
        }
        return;
    }

    const labels = windows.map(w => w.label || w.id || 'window');
    const metricsByWindow = windows.map(w => (w.metrics || {}));

    const metricSeries = {};
    function pushMetric(key, value) {
        if (!metricSeries[key]) metricSeries[key] = [];
        metricSeries[key].push(safeNum(value));
    }

    metricsByWindow.forEach((m, idx) => {
        const devs = (windows[idx].developers || []).length;
        const commits = (windows[idx].developers || []).reduce((s, d) => s + safeNum(d.commits_count), 0);
        const bugFix = (windows[idx].developers || []).reduce((s, d) => s + safeNum(d.bug_fix_commits_count), 0);
        const bugIntro = (windows[idx].developers || []).reduce((s, d) => s + safeNum(d.bug_introduced_count), 0);
        const abandonedCount = safeNum(m.abandoned_developers_count || 0);
        const abandonedRate = devs > 0 ? (abandonedCount / devs) : 0;

        pushMetric('loc', m.loc);
        pushMetric('nom', m.nom);
        pushMetric('developers', devs);
        pushMetric('commits', commits);
        pushMetric('bug_fix_commits', bugFix);
        pushMetric('bug_introduced', bugIntro);
        pushMetric('abandoned_developers', abandonedCount);
        pushMetric('abandoned_developers_rate', abandonedRate);

        const communityTotal = Object.values(m.community_smells_count || {}).reduce((s, n) => s + safeNum(n), 0);
        const mlTotal = Object.values(m.ml_smells_count || {}).reduce((s, n) => s + safeNum(n), 0);
        const traditionalTotal = Object.values(m.traditional_smells_count || {}).reduce((s, n) => s + safeNum(n), 0);
        const vulnTotal = Object.values(m.vulnerabilities_count || {}).reduce((s, n) => s + safeNum(n), 0);
        const sev = m.vulnerabilities_severity_count || {};

        pushMetric('community_smells_total', communityTotal);
        pushMetric('ml_smells_total', mlTotal);
        pushMetric('traditional_smells_total', traditionalTotal);
        pushMetric('vulnerabilities_total', vulnTotal);
        pushMetric('vulnerabilities_high', sev.HIGH || 0);
        pushMetric('vulnerabilities_medium', sev.MEDIUM || 0);
        pushMetric('vulnerabilities_low', sev.LOW || 0);

        const stqf = m.table3_metrics || {};
        Object.keys(stqf).forEach((k) => {
            pushMetric(`stqf.${k}`, stqf[k]);
        });
    });

    const metricKeys = Object.keys(metricSeries).sort((a, b) => a.localeCompare(b));
    const prevSelected = overallMetricSelect.value;
    overallMetricSelect.innerHTML = metricKeys
        .map(k => `<option value="${k}">${metricLabelFromKey(k)}</option>`)
        .join('');
    if (metricKeys.includes(prevSelected)) {
        overallMetricSelect.value = prevSelected;
    }
    if (!overallMetricSelect.value && metricKeys.length) {
        overallMetricSelect.value = metricKeys[0];
    }

    const selectedMetric = overallMetricSelect.value;
    const selectedValues = metricSeries[selectedMetric] || [];
    const trendCtx = document.getElementById('overallMetricTrendChart')?.getContext('2d');
    if (trendCtx) {
        if (overallMetricTrendChart) overallMetricTrendChart.destroy();
        overallMetricTrendChart = new Chart(trendCtx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: metricLabelFromKey(selectedMetric),
                    data: selectedValues,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.2)',
                    borderWidth: 2,
                    tension: 0.28,
                    fill: true,
                }]
            },
            options: {
                maintainAspectRatio: false,
                plugins: { legend: { labels: { color: '#e2e8f0' } } },
                scales: {
                    x: { ticks: { color: '#94a3b8' } },
                    y: { ticks: { color: '#94a3b8' } },
                }
            }
        });
    }

    overallMetricSelect.onchange = () => renderOverallStats(project);

    const baseColumns = [
        'loc', 'nom', 'developers', 'commits', 'bug_fix_commits', 'bug_introduced',
        'abandoned_developers', 'abandoned_developers_rate',
        'community_smells_total', 'ml_smells_total', 'traditional_smells_total',
        'vulnerabilities_total', 'vulnerabilities_high', 'vulnerabilities_medium', 'vulnerabilities_low'
    ];
    const stqfKeys = metricKeys.filter(k => k.startsWith('stqf.'));
    const allColumns = [...baseColumns, ...stqfKeys];

    const head = ['<thead><tr><th>Time Window</th>']
        .concat(allColumns.map(c => `<th>${escapeHtml(metricLabelFromKey(c))}</th>`))
        .concat(['</tr></thead>'])
        .join('');

    const bodyRows = windows.map((w, idx) => {
        const cells = allColumns.map((c) => {
            const value = metricSeries[c] ? metricSeries[c][idx] : 0;
            return `<td>${Number.isFinite(value) ? Number(value).toFixed(3).replace(/\.000$/, '') : '0'}</td>`;
        }).join('');
        return `<tr><td>${escapeHtml(w.label || w.id || 'window')}</td>${cells}</tr>`;
    }).join('');

    overallMetricsTimelineTable.innerHTML = `${head}<tbody>${bodyRows}</tbody>`;
    renderOverallDevelopersSummary(windows);
}

function getCurrentProjectIndex() {
    if (!currentProject || !Array.isArray(cachedProjects) || !cachedProjects.length) return -1;
    return cachedProjects.findIndex(p => p.id === currentProject.id);
}

function renderProjectPosition() {
    if (!projectPositionLabel) return;
    const idx = getCurrentProjectIndex();
    if (idx < 0 || !cachedProjects.length) {
        projectPositionLabel.innerText = 'Project 0/0';
        if (prevProjectBtn) prevProjectBtn.disabled = true;
        if (nextProjectBtn) nextProjectBtn.disabled = true;
        return;
    }
    projectPositionLabel.innerText = `Project ${idx + 1}/${cachedProjects.length}`;
    if (prevProjectBtn) prevProjectBtn.disabled = idx <= 0;
    if (nextProjectBtn) nextProjectBtn.disabled = idx >= cachedProjects.length - 1;
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    renderCommunityMetricsReference();
    fetchProjects();
    refreshGlobalTopics();
    loadLlmSettings();
});

if (projectRoleIntervalSelect) {
    projectRoleIntervalSelect.onchange = () => {
        if (currentProject) renderProjectRoleEvolution(currentProject);
    };
}

if (globalRoleIntervalSelect) {
    globalRoleIntervalSelect.onchange = () => {
        renderGlobalRoleEvolution(cachedProjects);
    };
}

if (analyzeProjectTopicsBtn) {
    analyzeProjectTopicsBtn.onclick = async () => {
        if (!currentProject) return;
        analyzeProjectTopicsBtn.disabled = true;
        analyzeProjectTopicsBtn.innerText = 'Analyzing...';
        if (projectTopicsStatus) projectTopicsStatus.innerHTML = 'Running standalone LLM topic and conflict extraction for this project...';
        try {
            const timeoutMs = computeLlmAnalysisTimeoutMs('project');
            if (projectTopicsStatus) {
                projectTopicsStatus.innerHTML = `Running standalone LLM topic and conflict extraction for this project... timeout budget: ${Math.round(timeoutMs / 60000)} min`;
            }
            const res = await fetchWithTimeout(`${API_URL}/projects/${currentProject.id}/topics/analyze`, { method: 'POST' }, timeoutMs);
            const body = await res.json();
            if (!res.ok) {
                alert(body?.detail || body?.error || 'Failed to analyze project topics.');
                return;
            }
            currentProject.topic_modeling = body;
            renderProjectTopics(currentProject);
            refreshGlobalTopics();
        } catch (err) {
            console.error('Project topic extraction failed', err);
            if (err?.name === 'AbortError') {
                alert(`Project LLM analysis timed out after about ${Math.round(computeLlmAnalysisTimeoutMs('project') / 60000)} minutes. Reduce LLM Runs or check the backend logs.`);
            } else {
                alert('Backend not reachable or topic extraction request failed.');
            }
        } finally {
            analyzeProjectTopicsBtn.disabled = false;
            analyzeProjectTopicsBtn.innerText = 'Run Project LLM Analysis';
        }
    };
}

if (analyzeGlobalTopicsBtn) {
    analyzeGlobalTopicsBtn.onclick = async () => {
        analyzeGlobalTopicsBtn.disabled = true;
        analyzeGlobalTopicsBtn.innerText = 'Analyzing...';
        if (globalTopicsStatus) globalTopicsStatus.innerHTML = 'Running global LLM aggregation across projects already prepared with Project LLM Analysis...';
        try {
            const timeoutMs = computeLlmAnalysisTimeoutMs('global');
            if (globalTopicsStatus) {
                globalTopicsStatus.innerHTML = `Running global LLM aggregation across projects already prepared with Project LLM Analysis... timeout budget: ${Math.round(timeoutMs / 60000)} min`;
            }
            const res = await fetchWithTimeout(`${API_URL}/topics/overall/analyze`, { method: 'POST' }, timeoutMs);
            const body = await res.json();
            if (!res.ok) {
                alert(body?.detail || body?.error || 'Failed to analyze global topics.');
                return;
            }
            renderTopicStatus(globalTopicsStatus, body, 'Completed');
            renderTopicTree(globalTopicsTree, body, 'global_topics');
        } catch (err) {
            console.error('Global topic extraction failed', err);
            if (err?.name === 'AbortError') {
                alert(`Global LLM analysis timed out after about ${Math.round(computeLlmAnalysisTimeoutMs('global') / 60000)} minutes. Reduce LLM Runs or analyze fewer projects first.`);
            } else {
                alert('Backend not reachable or topic extraction request failed.');
            }
        } finally {
            analyzeGlobalTopicsBtn.disabled = false;
            analyzeGlobalTopicsBtn.innerText = 'Run Global LLM Analysis';
        }
    };
}

if (saveLlmSettingsBtn) {
    saveLlmSettingsBtn.onclick = async () => {
        saveLlmSettingsBtn.disabled = true;
        saveLlmSettingsBtn.innerText = 'Saving...';
        if (llmSettingsStatus) llmSettingsStatus.innerHTML = 'Saving LLM settings...';
        try {
            const payload = {
                api_key: llmApiKeyInput?.value || '',
                github_token: githubTokenInput?.value || '',
                model: llmModelInput?.value || 'gpt-5-mini',
                llm_runs: Math.max(1, Math.min(7, Number(llmRunsInput?.value || 1) || 1)),
                organization: llmOrganizationInput?.value || '',
                project: llmProjectInput?.value || '',
                endpoint: llmEndpointInput?.value || 'https://api.openai.com/v1/chat/completions',
                clear_api_key: false,
                clear_github_token: false,
            };
            const res = await fetch(`${API_URL}/settings/llm`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const body = await res.json();
            if (!res.ok) {
                alert(body?.detail || 'Failed to save LLM settings.');
                return;
            }
            await loadLlmSettings();
        } catch (err) {
            console.error('Failed to save LLM settings', err);
            alert('Unable to save LLM settings.');
        } finally {
            saveLlmSettingsBtn.disabled = false;
            saveLlmSettingsBtn.innerText = 'Save LLM Settings';
        }
    };
}

if (clearLlmKeyBtn) {
    clearLlmKeyBtn.onclick = async () => {
        const ok = confirm('Clear the saved OpenAI API key and GitHub token from the backend settings?');
        if (!ok) return;
        clearLlmKeyBtn.disabled = true;
        clearLlmKeyBtn.innerText = 'Clearing...';
        try {
            const res = await fetch(`${API_URL}/settings/llm`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ clear_api_key: true, clear_github_token: true }),
            });
            const body = await res.json();
            if (!res.ok) {
                alert(body?.detail || 'Failed to clear the saved keys.');
                return;
            }
            await loadLlmSettings();
        } catch (err) {
            console.error('Failed to clear saved keys', err);
            alert('Unable to clear the saved keys.');
        } finally {
            clearLlmKeyBtn.disabled = false;
            clearLlmKeyBtn.innerText = 'Clear Saved Keys';
        }
    };
}

if (exportAllProjectsBtn) {
    exportAllProjectsBtn.onclick = () => {
        const url = `${API_URL}/projects/developers/export-all.csv?all_windows=true&analyzed_only=true`;
        window.open(url, '_blank');
    };
}

if (deleteAllProjectsBtn) {
    deleteAllProjectsBtn.onclick = async () => {
        const ok = confirm('Delete ALL projects from the list? This cannot be undone.');
        if (!ok) return;
        const second = confirm('Confirm again: this will remove all projects and managed cloned folders.');
        if (!second) return;

        const res = await fetch(`${API_URL}/projects`, { method: 'DELETE' });
        const body = await res.json();
        if (!res.ok) {
            alert(body?.detail || 'Failed to delete all projects.');
            return;
        }

        currentProject = null;
        currentWindowId = null;
        cachedProjects = [];
        projectDetailSection.classList.add('hidden');
        projectListSection.classList.remove('hidden');
        alert(`Deleted ${body.projects_deleted || 0} projects.`);
        fetchProjects();
    };
}

addProjectBtn.onclick = () => {
    document.getElementById('projName').value = '';
    document.getElementById('projUrls').value = '';
    document.getElementById('projPath').value = '';
    if (projCsvFileInput) projCsvFileInput.value = '';
    setBulkImportStatus('');
    addRepoPreviewIndex = 0;
    renderRepoListPreview();
    document.getElementById('advancedOptions').style.display = 'none';
    document.getElementById('toggleAdvanced').innerText = 'Show Advanced Options';
    addProjectModal.classList.remove('hidden');
};

document.getElementById('closeModal').onclick = () => addProjectModal.classList.add('hidden');
if (projUrlsInput) {
    projUrlsInput.oninput = () => {
        renderRepoListPreview();
    };
}
if (prevRepoInListBtn) {
    prevRepoInListBtn.onclick = () => {
        addRepoPreviewIndex -= 1;
        renderRepoListPreview();
    };
}
if (nextRepoInListBtn) {
    nextRepoInListBtn.onclick = () => {
        addRepoPreviewIndex += 1;
        renderRepoListPreview();
    };
}
async function runCsvImport(autoAnalyze = false) {
    const file = projCsvFileInput?.files?.[0];
    if (!file) {
        alert('Please select a CSV file first.');
        return;
    }
    let estimatedRows = 0;
    try {
        const txt = await file.text();
        estimatedRows = estimateCsvRowsFromText(txt);
    } catch (_) {
        estimatedRows = 0;
    }

    const secPerRepo = readImportSecPerRepo();
    const initialEtaSec = Math.round((estimatedRows || 1) * secPerRepo);
    const startTs = Date.now();
    setBulkImportStatus(`${autoAnalyze ? 'Import + full analysis' : 'Import'} started... estimated time ${formatEta(initialEtaSec)} (${estimatedRows || '?'} repos).`);
    if (importCsvBtn) importCsvBtn.disabled = true;
    if (importCsvAnalyzeBtn) importCsvAnalyzeBtn.disabled = true;
    if (projCsvFileInput) projCsvFileInput.disabled = true;
    let statusTimer = setInterval(() => {
        const elapsedSec = Math.max(1, Math.round((Date.now() - startTs) / 1000));
        const remaining = Math.max(initialEtaSec - elapsedSec, 0);
        setBulkImportStatus(
            `${autoAnalyze ? 'Import + full analysis' : 'Import'} in progress... elapsed ${formatEta(elapsedSec)} | ETA ${formatEta(remaining)} (${estimatedRows || '?'} repos).`
        );
    }, 1000);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('auto_analyze', autoAnalyze ? 'true' : 'false');
    formData.append('async_import', 'true');

    try {
        const res = await fetch(`${API_URL}/projects/import/csv`, {
            method: 'POST',
            body: formData,
        });
        const body = await res.json();
        if (!res.ok) {
            setBulkImportStatus(body?.detail || 'Failed to import CSV.', true);
            alert(body?.detail || 'Failed to import CSV.');
            return;
        }

        if (body?.mode === 'async') {
            clearInterval(statusTimer);
            const elapsedSec = Math.max(1, Math.round((Date.now() - startTs) / 1000));
            setBulkImportStatus(
                `${autoAnalyze ? 'Import + full analysis' : 'Import'} job started (${Number(body.requested || estimatedRows || 0)} repos). Elapsed ${formatEta(elapsedSec)}. Projects will appear progressively.`
            );
            alert(
                autoAnalyze
                    ? `Import started for ${Number(body.requested || 0)} repositories. Full analyses will start as soon as each repository is loaded.`
                    : `Import started for ${Number(body.requested || 0)} repositories. No analysis has been started automatically.`
            );
            addProjectModal.classList.add('hidden');
            fetchProjects();
            return;
        }

        const elapsedSec = Math.max(1, Math.round((Date.now() - startTs) / 1000));
        const createdCount = Array.isArray(body.created) ? body.created.length : 0;
        const errorCount = Array.isArray(body.errors) ? body.errors.length : 0;
        const requestedCount = Number(body.requested || (createdCount + errorCount) || estimatedRows || 1);
        writeImportSecPerRepo(elapsedSec / Math.max(requestedCount, 1));

        if (errorCount) {
            const sample = body.errors.slice(0, 3).map(ei => `${ei.url || `#${ei.index}`}: ${ei.error}`).join('\n');
            setBulkImportStatus(`Import completed in ${formatEta(elapsedSec)}. Created ${createdCount}, failed ${errorCount}.`, true);
            alert(`Imported ${createdCount} repositories, ${errorCount} failed.\n${sample}`);
        } else {
            setBulkImportStatus(`Import completed in ${formatEta(elapsedSec)}. Created ${createdCount} repositories.`);
            alert(
                autoAnalyze
                    ? `Imported ${createdCount} repositories and started full analysis.`
                    : `Imported ${createdCount} repositories without starting analysis.`
            );
        }

        if (createdCount > 0) {
            addProjectModal.classList.add('hidden');
            fetchProjects();
        }
    } finally {
        clearInterval(statusTimer);
        if (importCsvBtn) importCsvBtn.disabled = false;
        if (importCsvAnalyzeBtn) importCsvAnalyzeBtn.disabled = false;
        if (projCsvFileInput) projCsvFileInput.disabled = false;
    }
}

if (importCsvBtn) {
    importCsvBtn.onclick = async () => {
        await runCsvImport(true);
    };
}

if (importCsvAnalyzeBtn) {
    importCsvAnalyzeBtn.onclick = async () => {
        await runCsvImport(true);
    };
}

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

async function runAddProjects(autoAnalyze = false) {
    const name = document.getElementById('projName').value.trim();
    const urlsRaw = document.getElementById('projUrls').value;
    const path = document.getElementById('projPath').value.trim();
    const urls = parseRepoUrlList(urlsRaw);
    const submitBtn = ensureAddAnalyzeBtn();
    const addOnlyBtn = ensureAddProjectBtnModal();

    if (!urls.length) {
        alert('Please provide at least one repository URL.');
        return;
    }

    if (urls.length > 1 && path) {
        alert('Local path can be used only when adding a single repository.');
        return;
    }

    if (urls.length === 1) {
        try {
            if (addOnlyBtn) {
                addOnlyBtn.disabled = true;
                addOnlyBtn.innerText = autoAnalyze ? 'Adding...' : 'Adding...';
            }
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerText = 'Adding...';
            }
            setBulkImportStatus(autoAnalyze ? 'Creating project and starting full analysis...' : 'Creating project...');

            const url = urls[0];
            const inferredName = url.replace(/\/+$/, '').split('/').pop()?.replace(/\.git$/, '') || 'repository';
            const projectName = name || inferredName;
            const repositories = [{ url, name: projectName, local_path: path || '' }];
            const res = await fetch(`${API_URL}/projects/bulk?async_import=true`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ repositories, auto_analyze: autoAnalyze }),
            });
            const body = await res.json();
            if (!res.ok) {
                alert(body?.detail || 'Failed to add project.');
                return;
            }

            if (body?.mode === 'async') {
                setBulkImportStatus(
                    autoAnalyze
                        ? 'Project queued. Repository import started in background and full analysis will start automatically.'
                        : 'Project queued. Repository import started in background.'
                );
                addProjectModal.classList.add('hidden');
                fetchProjects();
                return;
            }

            setBulkImportStatus(autoAnalyze ? 'Project created. Full analysis started.' : 'Project created. No analysis started.');
            addProjectModal.classList.add('hidden');
            fetchProjects();
            return;
        } catch (err) {
            console.error('Add project failed', err);
            alert('Backend not reachable on http://127.0.0.1:8001. Start the server and try again.');
            setBulkImportStatus('Backend not reachable on http://127.0.0.1:8001.', true);
            return;
        } finally {
            if (addOnlyBtn) {
                addOnlyBtn.disabled = false;
                addOnlyBtn.innerText = 'Add Project';
            }
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerText = 'Add & Full Analysis';
            }
        }
    }

    try {
        if (addOnlyBtn) {
            addOnlyBtn.disabled = true;
            addOnlyBtn.innerText = 'Adding...';
        }
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerText = 'Adding...';
        }
        setBulkImportStatus(`Creating ${urls.length} projects${autoAnalyze ? ' and starting full analysis' : ''}...`);

        const repositories = urls.map((url, idx) => {
            const inferred = url.replace(/\/+$/, '').split('/').pop()?.replace(/\.git$/, '') || `repository-${idx + 1}`;
            const itemName = name ? `${name} ${idx + 1}` : inferred;
            return { url, name: itemName };
        });

        const res = await fetch(`${API_URL}/projects/bulk?async_import=true`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repositories, auto_analyze: autoAnalyze }),
        });
        const body = await res.json();
        if (!res.ok) {
            alert(body?.detail || 'Failed to add repositories.');
            return;
        }

        if (body?.mode === 'async') {
            setBulkImportStatus(
                autoAnalyze
                    ? `Queued ${Number(body.requested || urls.length || 0)} project(s). Import and full analysis are running in background.`
                    : `Queued ${Number(body.requested || urls.length || 0)} project(s). Import is running in background.`
            );
            addProjectModal.classList.add('hidden');
            fetchProjects();
            return;
        }

        const createdCount = Array.isArray(body.created) ? body.created.length : 0;
        const errorCount = Array.isArray(body.errors) ? body.errors.length : 0;
        if (errorCount) {
            const sample = body.errors.slice(0, 3).map(ei => `${ei.url || `#${ei.index}`}: ${ei.error}`).join('\n');
            alert(`Created ${createdCount} repositories, ${errorCount} failed.\n${sample}`);
        }

        if (createdCount) {
            setBulkImportStatus(
                autoAnalyze
                    ? `Created ${createdCount} project(s). Full analysis started.`
                    : `Created ${createdCount} project(s). No analysis started.`
            );
            addProjectModal.classList.add('hidden');
            fetchProjects();
        }
    } catch (err) {
        console.error('Bulk add project failed', err);
        alert('Backend not reachable on http://127.0.0.1:8001. Start the server and try again.');
        setBulkImportStatus('Backend not reachable on http://127.0.0.1:8001.', true);
    } finally {
        if (addOnlyBtn) {
            addOnlyBtn.disabled = false;
            addOnlyBtn.innerText = 'Add Project';
        }
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerText = 'Add & Full Analysis';
        }
    }
}

addProjectForm.onsubmit = async (e) => {
    e.preventDefault();
    await runAddProjects(true);
};

if (addProjectAnalyzeBtn) {
    addProjectAnalyzeBtn.onclick = async () => {
        await runAddProjects(true);
    };
}

function goToProjectsHome() {
    projectDetailSection.classList.add('hidden');
    projectListSection.classList.remove('hidden');
}

backBtn.onclick = () => {
    goToProjectsHome();
};

if (homeLogo) {
    homeLogo.onclick = () => {
        goToProjectsHome();
    };
    homeLogo.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            goToProjectsHome();
        }
    };
}

prevProjectBtn.onclick = () => {
    const idx = getCurrentProjectIndex();
    if (idx <= 0) return;
    showDetail(cachedProjects[idx - 1].id);
};

nextProjectBtn.onclick = () => {
    const idx = getCurrentProjectIndex();
    if (idx < 0 || idx >= cachedProjects.length - 1) return;
    showDetail(cachedProjects[idx + 1].id);
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
    document.getElementById('analysisStatus').innerText = 'Queued';
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
        cachedProjects = Array.isArray(projects) ? projects.slice() : [];
        renderProjectGrid(projects);
        renderGlobalRoleEvolution(cachedProjects);
        refreshGlobalTopics();

        const anyRunning = projects.some(p =>
            p.analysis_status === 'Running'
            || p.analysis_status === 'Queued'
            || p.analysis_status === 'Queued for automatic resume'
        );
        if (anyRunning && !pollInterval) {
            pollInterval = setInterval(fetchProjects, 5000);
        } else if (!anyRunning && pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }

        if (currentProject) {
            const updated = projects.find(p => p.id === currentProject.id);
            const shouldRefreshDetail = Boolean(updated) && (
                updated.analysis_status !== currentProject.analysis_status
                || updated.ml_detection_status !== currentProject.ml_detection_status
                || Number(updated.analysis_progress_pct || 0) !== Number(currentProject.analysis_progress_pct || 0)
                || Number(updated.analysis_eta_seconds ?? -1) !== Number(currentProject.analysis_eta_seconds ?? -1)
                || Number(updated.analysis_window_index || 0) !== Number(currentProject.analysis_window_index || 0)
                || Number(updated.analysis_window_total || 0) !== Number(currentProject.analysis_window_total || 0)
            );
            if (shouldRefreshDetail) {
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
        timeWindowSelect.innerHTML = '<option value="">No historical windows yet</option>';
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
    const preferredTab = overallTabBtn?.classList.contains('active') ? 'overall' : 'snapshot';
    currentProject = project;

    projectListSection.classList.add('hidden');
    projectDetailSection.classList.remove('hidden');

    document.getElementById('detailProjectName').innerText = project.name;
    document.getElementById('analysisStatus').innerText = project.analysis_status;
    const mlStatus = project.ml_detection_error
        ? `${project.ml_detection_status || 'Unknown'} (${project.ml_detection_error})`
        : (project.ml_detection_status || 'Unknown');
    document.getElementById('mlDetectionStatus').innerText = mlStatus;
    renderAnalysisEta(project);
    renderProjectPosition();

    switchDetailTab(preferredTab);
    renderTimeWindowSelector(project);
    renderSelectedWindow();
}

function renderSelectedWindow() {
    if (!currentProject) return;
    const selectedWindow = getSelectedWindow(currentProject);
    if (!selectedWindow) {
        renderTimeWindowSelector(currentProject);
        const status = currentProject.analysis_status || 'Unknown';
        timeWindowLabel.innerText = `No historical windows available (${status})`;
        document.getElementById('metricLoc').innerText = 0;
        document.getElementById('metricNom').innerText = 0;
        renderSmellChart({});
        renderCommunitySmellStatus({}, []);
        renderDeveloperList([]);
        renderNetwork([], []);
        renderDeveloperAnalytics([], {}, null);
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
    renderDeveloperAnalytics(selectedWindow.developers || [], m, selectedWindow);
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
    const abandonedIds = Array.isArray(metrics.abandoned_developers_ids) ? metrics.abandoned_developers_ids : [];
    const abandonedCount = Number(metrics.abandoned_developers_count || abandonedIds.length || 0);
    const abandonedHtml = abandonedCount > 0
        ? `<div style="margin-top:8px;"><b>Abandoned developers:</b> ${abandonedCount}<br><span style="color:#fda4af;">${escapeHtml(abandonedIds.join(', ') || 'n/a')}</span></div>`
        : '<div style="margin-top:8px;"><b>Abandoned developers:</b> 0</div>';

    if (total <= 0) {
        container.innerHTML = `<b>Community smells detected:</b> 0<br>No community smell was detected in this time window.${abandonedHtml}`;
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
        ${abandonedHtml}
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
        const abandonmentLine = d.is_abandoned
            ? `<div style="font-size: 0.78rem; color: #fda4af; margin-top: 6px;">
                    Abandonment: <b>Abandoned</b>${d.abandoned_since_window_label ? ` since <b>${escapeHtml(d.abandoned_since_window_label)}</b>` : ''}
               </div>`
            : `<div style="font-size: 0.78rem; color: #86efac; margin-top: 6px;">
                    Abandonment: <b>Active</b>${d.last_interaction_window_label ? ` (last interaction: ${escapeHtml(d.last_interaction_window_label)})` : ''}
               </div>`;

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
                ${abandonmentLine}
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

function networkColorForRole(classification) {
    return ROLE_COLOR_MAP[normalizeRoleLabel(classification)] || ROLE_COLOR_MAP.Unknown;
}

function buildNetworkNodes(developers) {
    return (developers || []).map((dev, idx) => ({
        id: idx,
        label: (dev.aliases && dev.aliases[0]) || (dev.id || '').split('@')[0],
        color: networkColorForRole(dev.classification),
        title: `ID: ${dev.id}\nRole: ${dev.classification}\nGender: ${dev.gender || 'Unknown'} (${Number(dev.gender_confidence || 0).toFixed(2)})\nSE: ${dev.se_score} | AI: ${dev.ai_score}\n` +
            `Sentiment: ${dev.sentiment_label || 'Unknown'} (${Number(dev.sentiment_score || 0).toFixed(3)})\n` +
            `Abandonment: ${dev.abandonment_status || (dev.is_abandoned ? 'Abandoned' : 'Active')}` +
            `${dev.abandoned_since_window_label ? ` (since ${dev.abandoned_since_window_label})` : ''}\n` +
            `Commits: ${dev.commits_count || 0} | Fixes: ${dev.bug_fix_commits_count || 0}\n` +
            `Files touched: ${dev.files_touched_count || 0} | Churn: ${dev.code_churn || 0}\n` +
            `Bug-inducing commits (R-SZZ): ${dev.bug_introduced_count || 0}\n` +
            ((dev.community_smells || []).length ? `Community smells: ${(dev.community_smells || []).join(', ')}\n` : '') +
            ((dev.ml_smells || []).length ? `ML smells: ${(dev.ml_smells || []).join(', ')}\n` : '') +
            ((dev.traditional_smells || []).length ? `Traditional smells: ${(dev.traditional_smells || []).join(', ')}\n` : '') +
            ((dev.vulnerabilities || []).length ? `Vulnerabilities: ${(dev.vulnerabilities || []).join(', ')}` : '')
    }));
}

function buildNetworkEdges(edgesData) {
    const edgeLengthFromWeight = (weight) => {
        const safeWeight = Math.max(1, Number(weight) || 1);
        const rawLength = 280 / Math.sqrt(safeWeight);
        return Math.max(80, Math.min(420, rawLength));
    };

    return (edgesData || []).map((e, i) => {
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
}

function buildVisNetworkOptions() {
    return {
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
}

function renderNetwork(developers, edgesData) {
    const container = document.getElementById('networkGraph');
    if (!container) return;
    if (snapshotNetworkChart) snapshotNetworkChart.destroy();

    const nodes = buildNetworkNodes(developers);
    const edges = buildNetworkEdges(edgesData);
    const data = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(edges)
    };
    snapshotNetworkChart = new vis.Network(container, data, buildVisNetworkOptions());
}

function buildOverallNetworkData(project) {
    const windows = collectOverallWindows(project);
    const devById = new Map();
    const edgeByPair = new Map();

    windows.forEach((w) => {
        const windowDevs = Array.isArray(w.developers) ? w.developers : [];
        windowDevs.forEach((d) => {
            if (!d || !d.id) return;
            const existing = devById.get(d.id);
            if (!existing) {
                devById.set(d.id, { ...d });
                return;
            }
            if ((Number(d.commits_count) || 0) > (Number(existing.commits_count) || 0)) {
                devById.set(d.id, { ...existing, ...d });
            }
        });

        (w.collaboration_edges || []).forEach((e) => {
            const fromDev = windowDevs[e.from];
            const toDev = windowDevs[e.to];
            if (!fromDev || !toDev || !fromDev.id || !toDev.id || fromDev.id === toDev.id) return;
            const a = String(fromDev.id);
            const b = String(toDev.id);
            const key = a < b ? `${a}||${b}` : `${b}||${a}`;
            edgeByPair.set(key, (edgeByPair.get(key) || 0) + Math.max(1, Number(e.weight) || 1));
        });
    });

    const developers = Array.from(devById.values()).sort((a, b) => String(a.id).localeCompare(String(b.id)));
    const idxById = new Map(developers.map((d, i) => [d.id, i]));
    const edges = Array.from(edgeByPair.entries()).map(([pair, weight]) => {
        const [a, b] = pair.split('||');
        return {
            from: idxById.get(a),
            to: idxById.get(b),
            weight,
        };
    }).filter((e) => Number.isInteger(e.from) && Number.isInteger(e.to));

    return { developers, edges };
}

function renderOverallNetwork(project) {
    const container = document.getElementById('overallNetworkGraph');
    if (!container) return;
    if (overallNetworkChart) overallNetworkChart.destroy();

    const { developers, edges } = buildOverallNetworkData(project);
    if (!developers.length) {
        container.innerHTML = '<div style="color:#94a3b8; padding:0.7rem;">No network data available yet.</div>';
        return;
    }
    container.innerHTML = '';

    const nodes = buildNetworkNodes(developers);
    const normalizedEdges = buildNetworkEdges(edges);
    const data = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(normalizedEdges)
    };
    overallNetworkChart = new vis.Network(container, data, buildVisNetworkOptions());
}

function normalizeAbandonmentRoleBucket(classification) {
    return normalizeRoleLabel(classification);
}

function findDeveloperInHistory(devId, maxWindowIdx) {
    if (!currentProject || !Array.isArray(currentProject.time_windows)) return null;
    const windows = currentProject.time_windows || [];
    const end = Math.min(Math.max(Number(maxWindowIdx) || 0, 0), windows.length - 1);
    for (let idx = end; idx >= 0; idx -= 1) {
        const dev = (windows[idx].developers || []).find((d) => d.id === devId);
        if (dev) return dev;
    }
    return null;
}

function renderDeveloperAnalytics(developers, metrics = {}, currentWindow = null) {
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
        const role = normalizeRoleLabel(d.classification);
        roleCounts[role] = (roleCounts[role] || 0) + 1;
    });

    const abandonedRoleBuckets = {
        'Software Engineer': 0,
        'AI/ML Engineer': 0,
        'Hybrid': 0,
        'Unknown': 0,
    };
    const seenAbandoned = new Set();
    const windows = (currentProject && Array.isArray(currentProject.time_windows)) ? currentProject.time_windows : [];
    const currentWindowIdx = currentWindow ? windows.findIndex((w) => w.id === currentWindow.id) : -1;
    const abandonedIds = Array.isArray(metrics.abandoned_developers_ids) ? metrics.abandoned_developers_ids : [];

    abandonedIds.forEach((devId) => {
        if (!devId || seenAbandoned.has(devId)) return;
        seenAbandoned.add(devId);
        const fromCurrent = (developers || []).find((d) => d.id === devId);
        const hist = fromCurrent || findDeveloperInHistory(devId, currentWindowIdx >= 0 ? currentWindowIdx : windows.length - 1);
        const bucket = normalizeAbandonmentRoleBucket(hist?.classification);
        abandonedRoleBuckets[bucket] += 1;
    });

    // Fallback for datasets that still expose abandoned devs directly in the selected window.
    developers
        .filter((d) => !!d.is_abandoned && !seenAbandoned.has(d.id))
        .forEach((d) => {
            seenAbandoned.add(d.id);
            const bucket = normalizeAbandonmentRoleBucket(d.classification);
            abandonedRoleBuckets[bucket] += 1;
        });

    if (devCommitsChart) devCommitsChart.destroy();
    if (devBugsChart) devBugsChart.destroy();
    if (devChurnChart) devChurnChart.destroy();
    if (devRoleChart) devRoleChart.destroy();
    if (abandonedRoleChart) abandonedRoleChart.destroy();
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
                backgroundColor: Object.keys(roleCounts).map((role) => ROLE_COLOR_MAP[normalizeRoleLabel(role)] || ROLE_COLOR_MAP.Unknown)
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

    const abandonedRoleLabels = Object.keys(abandonedRoleBuckets);
    const abandonedRoleValues = Object.values(abandonedRoleBuckets);
    const abandonedTotal = abandonedRoleValues.reduce((s, n) => s + (Number(n) || 0), 0);
    const pieLabels = abandonedTotal > 0 ? abandonedRoleLabels : ['No Abandonment'];
    const pieValues = abandonedTotal > 0 ? abandonedRoleValues : [1];
    const pieColors = abandonedTotal > 0
        ? abandonedRoleLabels.map((role) => ROLE_COLOR_MAP[normalizeRoleLabel(role)] || ROLE_COLOR_MAP.Unknown)
        : ['#334155'];
    abandonedRoleChart = new Chart(document.getElementById('abandonedRoleChart').getContext('2d'), {
        type: 'pie',
        data: {
            labels: pieLabels,
            datasets: [{
                data: pieValues,
                backgroundColor: pieColors
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
