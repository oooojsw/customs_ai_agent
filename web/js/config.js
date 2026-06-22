// API 配置
// 强制使用 127.0.0.1 避免 Windows 下 localhost 解析错误
const BASE_URL = 'http://127.0.0.1:8000/api/v1'; 
const AGENT_V1_BASE_URL = 'http://127.0.0.1:8000/api/agent/v1';

const REPORT_API_URL = `${BASE_URL}/generate_report`;
const AGENT_RUNS_URL = `${AGENT_V1_BASE_URL}/runs`;
const ANALYZE_URL = `${BASE_URL}/analyze`;
const QUERY_URL = `${BASE_URL}/query/declaration/`;
const IMAGE_API_URL = `${BASE_URL}/analyze_image`;

// Agent V1 演示身份。平台接入后由平台登录态提供这些字段。
const SESSION_STORAGE_KEY = 'customs_agent_session_id';
const SESSION_ID = sessionStorage.getItem(SESSION_STORAGE_KEY)
    || `web-session-${Date.now()}`;
sessionStorage.setItem(SESSION_STORAGE_KEY, SESSION_ID);
const USER_ID = localStorage.getItem('customs_agent_user_id') || 'web-demo-user';
const TENANT_ID = 'web-demo';
