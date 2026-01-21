// 语言包配置
const translations = {
    zh: {
        // 导航
        settings: '设置',
        language: '语言',
        nav_audit: '审单',
        nav_chat: '咨询',
        nav_report: '合规建议',

        // Header
        system_title: '智能报关系统',
        system_subtitle: '智慧口岸自动化报关辅助决策系统 v3.0 Pro',
        status_online: '系统在线',
        model_info: 'deepseek-v3/r1',

        // 审单模块
        audit_title: '单据研判',
        search_placeholder: '输入报关单号...',
        search_btn: '查询',
        image_recognition: '图片识别 (OCR)',
        image_support: '支持 jpg/png, Max 20MB',
        select_image: '选择图片',
        recognize_btn: '识别',
        import_data: '引用数据',
        raw_data_placeholder: '在此粘贴报关数据...',
        start_analysis: '开始智能研判',
        decision_flow: '决策推理流',
        executing: '执行中',
        system_ready: '系统待命 SYSTEM READY',

        // 咨询模块
        chat_assistant: '咨询助手',
        rag_connected: 'RAG 知识库已连接',
        ai_welcome: '👋 您好！我是您的海关法规专家。我可以帮您查询归类规则、税率政策或监管条件。',
        chat_placeholder: '请输入问题...',

        // 报告模块
        compliance_audit: '智能合规审计',
        standard_mode: '标准版',
        pro_mode: 'Pro',
        import_from_audit: '引用数据',
        terminate: '终止',
        generate_report: '生成报告',
        start_deep_analysis: '启动深度研判引擎',
        case_file: '案件档案 / 研判主题',
        imported: '已导入',
        report_placeholder: '请在此输入：\n1. 报关单据原文（触发合规模式）\n2. 或任意研究主题（触发深度研判模式）...',
        waiting_task: '等待任务启动...',
        report_area: 'AI 审计/研判报告生成区',
        evidence_chain: '审计证据链',
        waiting_search: '等待检索启动...',
        searching: '正在检索',
        ai_thought_log: 'AI_THOUGHT_LOG',
        live: '● LIVE',

        // 通用
        thinking: '思考中...',
        error: '错误',
        waiting: '等待...',
        none: '暂无',
        loading: '加载中...',
        analyzing: '研判中...',
        connecting_brain: '正在连接大脑...',
        user_terminated: '用户已手动终止生成',
        generation_error: '生成错误',
        generation_interrupted: '生成中断',
        report_completed: '审计报告生成完毕',

        // 审单模块
        please_input_id: '请输入单号',
        no_data_found: '未找到数据',
        query_failed: '查询失败',
        please_input_data: '请输入数据',
        request_failed: '请求失败',
        view_reference_file: '查看参考文件',
        no_rag_file: '未找到对应的 RAG 文件',
        load_file_failed: '加载文件失败',
        no_file_content: '未找到对应文件内容',
        audit_pass: '智能研判通过',
        audit_risk: '发现潜在风险',
        decision_summary: '决策摘要',
        custom_data_label: '【报关数据】',
        preliminary_conclusion_label: '【初审结论】',
        no_audit_data: '无审单数据',
        please_input_data_first: '请先输入数据',
        select_image_first: '请先选择一张报关单图片！',
        recognition_error: '识别服务异常',
        image_recognition_failed: '图片识别失败:',

        // 样本按钮
        sample10: '✅ 10.完美机械',
        sample7: '✅ 7.免费样品',
        sample1: '❌ 1.归类欺诈',
        sample2: '❌ 2.洋垃圾',
        sample3: '❌ 3.重量误差',
        sample4: '❌ 4.要素模糊',
        sample5: '❌ 5.价格洗钱',
        sample6: '❌ 6.濒危红木',
        sample8: '❌ 8.两用物项',
        sample9: '❌ 9.币制错误',
    },

    vi: {
        // 导航
        settings: 'Cài đặt',
        language: 'Ngôn ngữ',
        nav_audit: 'Kiểm tra',
        nav_chat: 'Tư vấn',
        nav_report: 'Đề xuất tuân thủ',

        // Header
        system_title: 'Hệ thống Hải quan Thông minh',
        system_subtitle: 'Hệ thống hỗ trợ quyết định khai báo hải quan tự động v3.0 Pro',
        status_online: 'Hệ thống trực tuyến',
        model_info: 'deepseek-v3/r1',

        // 审单模块
        audit_title: 'Phân tích chứng từ',
        search_placeholder: 'Nhập số tờ khai...',
        search_btn: 'Tra cứu',
        image_recognition: 'Nhận dạng hình ảnh (OCR)',
        image_support: 'Hỗ trợ jpg/png, Tối đa 20MB',
        select_image: 'Chọn ảnh',
        recognize_btn: 'Nhận dạng',
        import_data: 'Nhập dữ liệu',
        raw_data_placeholder: 'Dán dữ liệu khai báo hải quan vào đây...',
        start_analysis: 'Bắt đầu phân tích thông minh',
        decision_flow: 'Dòng chảy quyết định',
        executing: 'Đang thực thi',
        system_ready: 'Hệ thống sẵn sàng SYSTEM READY',

        // 咨询模块
        chat_assistant: 'Trợ lý Tư vấn',
        rag_connected: 'Đã kết nối cơ sở kiến thức RAG',
        ai_welcome: '👋 Xin chào! Tôi là chuyên gia về quy định hải quan của bạn. Tôi có thể giúp bạn tra cứu quy tắc phân loại, chính sách thuế hoặc điều kiện giám sát.',
        chat_placeholder: 'Nhập câu hỏi...',

        // 报告模块
        compliance_audit: 'Kiểm toán Tuân thủ Thông minh',
        standard_mode: 'Tiêu chuẩn',
        pro_mode: 'Pro',
        import_from_audit: 'Nhập dữ liệu',
        terminate: 'Dừng',
        generate_report: 'Tạo báo cáo',
        start_deep_analysis: 'Khởi động động cơ phân tích sâu',
        case_file: 'Hồ sơ vụ việc / Chủ đề nghiên cứu',
        imported: 'Đã nhập',
        report_placeholder: 'Vui lòng nhập:\n1. Văn bản tờ khai hải quan (kích hoạt chế độ tuân thủ)\n2. Hoặc bất kỳ chủ đề nghiên cứu nào (kích hoạt chế độ phân tích sâu)...',
        waiting_task: 'Chờ bắt đầu nhiệm vụ...',
        report_area: 'Khu vực tạo báo cáo kiểm toán/phân tích AI',
        evidence_chain: 'Chuỗi bằng chứng kiểm toán',
        waiting_search: 'Chờ khởi động tìm kiếm...',
        searching: 'Đang tìm kiếm',
        ai_thought_log: 'AI_THOUGHT_LOG',
        live: '● TRỰC TIẾP',

        // 通用
        thinking: 'Đang suy nghĩ...',
        error: 'Lỗi',
        waiting: 'Đang chờ...',
        none: 'Không có',
        loading: 'Đang tải...',
        analyzing: 'Đang phân tích...',
        connecting_brain: 'Đang kết nối não...',
        user_terminated: 'Người dùng đã thủ công dừng tạo',
        generation_error: 'Lỗi tạo',
        generation_interrupted: 'Tạo bị gián đoạn',
        report_completed: 'Đã tạo xong báo cáo kiểm toán',

        // 审单模块
        please_input_id: 'Vui lòng nhập số tờ khai',
        no_data_found: 'Không tìm thấy dữ liệu',
        query_failed: 'Tra cứu thất bại',
        please_input_data: 'Vui lòng nhập dữ liệu',
        request_failed: 'Yêu cầu thất bại',
        view_reference_file: 'Xem tệp tham khảo',
        no_rag_file: 'Không tìm thấy tệp RAG tương ứng',
        load_file_failed: 'Tải tệp thất bại',
        no_file_content: 'Không tìm thấy nội dung tệp tương ứng',
        audit_pass: 'Phân tích thông minh đạt',
        audit_risk: 'Phát hiện rủi ro tiềm ẩn',
        decision_summary: 'Tóm tắt quyết định',
        custom_data_label: '【Dữ liệu khai báo】',
        preliminary_conclusion_label: '【Kết luận sơ bộ】',
        no_audit_data: 'Không có dữ liệu kiểm toán',
        please_input_data_first: 'Vui lòng nhập dữ liệu trước',
        select_image_first: 'Vui lòng chọn một hình ảnh tờ khai hải quan trước!',
        recognition_error: 'Lỗi dịch vụ nhận dạng',
        image_recognition_failed: 'Nhận dạng hình ảnh thất bại:',

        // 样本按钮
        sample10: '✅ 10.Cơ khí hoàn hảo',
        sample7: '✅ 7.Mẫu miễn phí',
        sample1: '❌ 1.Lừa đảo phân loại',
        sample2: '❌ 2.Rác thải',
        sample3: '❌ 3.Lỗi trọng lượng',
        sample4: '❌ 4.Thông tin mờ nhạt',
        sample5: '❌ 5.Rửa tiền giá',
        sample6: '❌ 6.Gỗ quý hiếm',
        sample8: '❌ 8.Hàng hóa lưỡng dụng',
        sample9: '❌ 9.Lỗi tiền tệ',
    }
};

// 当前语言 - 挂载到 window 对象使其成为全局变量
window.currentLanguage = localStorage.getItem('language') || 'zh';

// 获取翻译文本
function t(key) {
    return translations[window.currentLanguage][key] || translations['zh'][key] || key;
}

// 设置语言
function setLanguage(lang) {
    window.currentLanguage = lang;
    localStorage.setItem('language', lang);

    // 更新按钮样式
    const zhBtn = document.getElementById('lang-zh');
    const viBtn = document.getElementById('lang-vi');

    if (lang === 'zh') {
        zhBtn.className = 'flex-1 py-2 bg-cyan-600 text-white rounded text-sm font-bold transition';
        viBtn.className = 'flex-1 py-2 bg-slate-700 text-slate-300 rounded text-sm font-bold hover:bg-slate-600 transition';
    } else {
        zhBtn.className = 'flex-1 py-2 bg-slate-700 text-slate-300 rounded text-sm font-bold hover:bg-slate-600 transition';
        viBtn.className = 'flex-1 py-2 bg-cyan-600 text-white rounded text-sm font-bold transition';
    }

    // 更新页面所有带 data-i18n 的元素
    updatePageLanguage();

    // 自动关闭弹窗
    document.getElementById('settingsModal').classList.add('hidden');
}

// 更新页面语言
function updatePageLanguage() {
    const elements = document.querySelectorAll('[data-i18n]');
    elements.forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
    });

    // 更新 placeholder 属性
    const placeholders = document.querySelectorAll('[data-i18n-placeholder]');
    placeholders.forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        el.placeholder = t(key);
    });

    // 更新 value 属性（用于输入框的默认值）
    const values = document.querySelectorAll('[data-i18n-value]');
    values.forEach(el => {
        const key = el.getAttribute('data-i18n-value');
        el.value = t(key);
    });
}

// 切换设置弹窗
function toggleSettings() {
    const modal = document.getElementById('settingsModal');
    modal.classList.toggle('hidden');
}

// 页面加载时初始化语言
document.addEventListener('DOMContentLoaded', () => {
    setLanguage(window.currentLanguage);
});
