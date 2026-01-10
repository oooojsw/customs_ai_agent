// API 配置
const BASE_URL = 'http://localhost:8000/api/v1';
const REPORT_API_URL = `${BASE_URL}/generate_report`;
const CHAT_URL = `${BASE_URL}/chat`;
const ANALYZE_URL = `${BASE_URL}/analyze`;
const QUERY_URL = `${BASE_URL}/query/declaration/`;
const IMAGE_API_URL = `${BASE_URL}/analyze_image`;

// 全局会话 ID
const SESSION_ID = 'session-' + Date.now();