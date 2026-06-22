// ----------------------------------------------------
// 公共：模块切换
// ----------------------------------------------------
function switchModule(id) {
    const targetNav = document.getElementById('nav-' + id);
    if (!targetNav || targetNav.classList.contains('hidden')) return;
    document.querySelectorAll('.module-content').forEach(el => el.classList.add('hidden'));
    document.getElementById('module-' + id).classList.remove('hidden');
    document.querySelectorAll('nav button').forEach(b => b.classList.remove('nav-active'));
    document.getElementById('nav-' + id).classList.add('nav-active');

    // 修复聊天滚动
    if(id === 'chat') {
        const h = document.getElementById('chatHistory');
        h.scrollTop = h.scrollHeight;
    }
}

const NAVIGATION_PREFERENCES_KEY = 'customs_navigation_preferences_v2';

function getNavigationPreferences() {
    const defaults = { audit: false, report: false, sidebarCollapsed: false };
    try {
        const stored = JSON.parse(localStorage.getItem(NAVIGATION_PREFERENCES_KEY) || '{}');
        return { ...defaults, ...stored };
    } catch (_) {
        return defaults;
    }
}

function saveNavigationPreferences(preferences) {
    localStorage.setItem(NAVIGATION_PREFERENCES_KEY, JSON.stringify(preferences));
}

function applyFeatureNavigation(preferences = getNavigationPreferences()) {
    const auditNav = document.getElementById('nav-audit');
    const reportNav = document.getElementById('nav-report');
    const auditToggle = document.getElementById('showAuditNavToggle');
    const reportToggle = document.getElementById('showReportNavToggle');

    auditNav?.classList.toggle('hidden', !preferences.audit);
    reportNav?.classList.toggle('hidden', !preferences.report);
    if (auditToggle) auditToggle.checked = preferences.audit;
    if (reportToggle) reportToggle.checked = preferences.report;

    const auditVisible = !document.getElementById('module-audit')?.classList.contains('hidden');
    const reportVisible = !document.getElementById('module-report')?.classList.contains('hidden');
    if ((auditVisible && !preferences.audit) || (reportVisible && !preferences.report)) {
        switchModule('chat');
    }
}

function setFeatureNavigation(feature, visible) {
    if (!['audit', 'report'].includes(feature)) return;
    const preferences = getNavigationPreferences();
    preferences[feature] = Boolean(visible);
    saveNavigationPreferences(preferences);
    applyFeatureNavigation(preferences);
}

function setSidebarCollapsed(collapsed) {
    const sidebar = document.getElementById('appSidebar');
    const expandButton = document.getElementById('sidebarExpandBtn');
    if (!sidebar || !expandButton) return;

    sidebar.classList.toggle('hidden', collapsed);
    expandButton.classList.toggle('hidden', !collapsed);
    expandButton.classList.toggle('flex', collapsed);

    const preferences = getNavigationPreferences();
    preferences.sidebarCollapsed = Boolean(collapsed);
    saveNavigationPreferences(preferences);
}

// ----------------------------------------------------
// 页面初始化
// ----------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const navigationPreferences = getNavigationPreferences();
    applyFeatureNavigation(navigationPreferences);
    setSidebarCollapsed(navigationPreferences.sidebarCollapsed);

    // 初始化聊天滚动监听器
    if (typeof initChatScrollListener === 'function') {
        initChatScrollListener();
    }
});
