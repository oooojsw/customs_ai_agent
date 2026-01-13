// API 配置
// 强制使用 127.0.0.1 避免 Windows 下 localhost 解析错误
const BASE_URL = 'http://127.0.0.1:8000/api/v1'; 

const REPORT_API_URL = `${BASE_URL}/generate_report`;
const CHAT_URL = `${BASE_URL}/chat`;
const ANALYZE_URL = `${BASE_URL}/analyze`;
const QUERY_URL = `${BASE_URL}/query/declaration/`;
const IMAGE_API_URL = `${BASE_URL}/analyze_image`;

// 全局会话 ID
const SESSION_ID = 'session-' + Date.now();