// 语言包配置
const translations = {
    zh: {
        // 导航
        settings: '设置',
        language: '语言',
        nav_audit: '审单',
        nav_chat: '智能体',
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
        chat_assistant: '智能体',
        rag_connected: 'RAG 知识库已连接',
        ai_welcome: '👋 您好！我是海关智能体。我可以帮您调用各类工具，包括智能审单、法规检索等，为您提供专业的报关辅助服务。',
        chat_placeholder: '请输入问题...',

        // 工具调用状态
        tool_audit_declaration: '智能审单',
        tool_search_customs_regulations: '法规检索',
        tool_query_exchange_rate: '汇率查询',
        tool_calling: '正在调用工具',
        tool_call_done: '调用完毕',

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

        // 索引管理
        index_management: '知识库索引',
        rebuild_index: '重建索引',
        rebuilding: '重建中...',
        index_initializing: '初始化...',
        index_processing: '处理中',
        index_complete: '索引重建完成',
        index_cancelled: '索引重建已取消',
        index_error: '索引重建失败',
        total_files: '文件总数',
        total_chunks: '片段总数',

        // LLM 配置
        llm_config_title: 'LLM 模型配置',
        use_custom_config: '使用自定义配置',
        provider: '服务商',
        base_url: 'API 地址',
        model_name: '模型名称',
        test_connection: '测试连接',
        save_and_reload: '保存并应用',
        reset_to_env: '重置为 .env',
        config_saved: '配置已保存',
        config_applied: '配置已应用',
        test_success: '测试成功',
        test_failed: '测试失败',

        // 图像配置
        image_config_title: '图像识别模型配置',
        use_custom_image_config: '使用自定义配置',
    },

    vi: {
        // 导航
        settings: 'Cài đặt',
        language: 'Ngôn ngữ',
        nav_audit: 'Kiểm tra',
        nav_chat: 'Tác nhân thông minh',
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
        chat_assistant: 'Tác nhân thông minh',
        rag_connected: 'Đã kết nối cơ sở kiến thức RAG',
        ai_welcome: '👋 Xin chào! Tôi là tác nhân thông minh hải quan. Tôi có thể giúp bạn gọi các công cụ khác nhau, bao gồm kiểm tra hải quan thông minh, tra cứu quy chế, v.v., để cung cấp dịch vụ hỗ trợ khai báo hải quan chuyên nghiệp.',
        chat_placeholder: 'Nhập câu hỏi...',

        // 工具调用状态
        tool_audit_declaration: 'Kiểm tra hải quan',
        tool_search_customs_regulations: 'Tra cứu quy chế',
        tool_query_exchange_rate: 'Tra cứu tỷ giá',
        tool_calling: 'Đang gọi công cụ',
        tool_call_done: 'Hoàn thành',

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

        // 索引管理
        index_management: 'Chỉ mục cơ sở kiến thức',
        rebuild_index: 'Xây dựng lại chỉ mục',
        rebuilding: 'Đang xây dựng...',
        index_initializing: 'Khởi tạo...',
        index_processing: 'Đang xử lý',
        index_complete: 'Xây dựng chỉ mục hoàn thành',
        index_cancelled: 'Xây dựng chỉ mục đã hủy',
        index_error: 'Xây dựng chỉ mục thất bại',
        total_files: 'Tổng số tệp',
        total_chunks: 'Tổng số đoạn',

        // LLM 配置
        llm_config_title: 'Cấu hình LLM',
        use_custom_config: 'Sử dụng cấu hình tùy chỉnh',
        provider: 'Nhà cung cấp',
        base_url: 'Địa chỉ API',
        model_name: 'Tên mô hình',
        test_connection: 'Kiểm tra kết nối',
        save_and_reload: 'Lưu và áp dụng',
        reset_to_env: 'Đặt lại về .env',
        config_saved: 'Đã lưu cấu hình',
        config_applied: 'Đã áp dụng cấu hình',
        test_success: 'Kiểm tra thành công',
        test_failed: 'Kiểm tra thất bại',

        // 图像配置
        image_config_title: 'Cấu hình mô hình nhận dạng hình ảnh',
        use_custom_image_config: 'Sử dụng cấu hình tùy chỉnh',
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
        zhBtn.className = 'p-6 bg-gradient-to-br from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-lg shadow-lg transition transform hover:scale-105 ring-2 ring-cyan-400';
        viBtn.className = 'p-6 bg-gradient-to-br from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white rounded-lg shadow-lg transition transform hover:scale-105';
    } else {
        zhBtn.className = 'p-6 bg-gradient-to-br from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-lg shadow-lg transition transform hover:scale-105';
        viBtn.className = 'p-6 bg-gradient-to-br from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white rounded-lg shadow-lg transition transform hover:scale-105 ring-2 ring-purple-400';
    }

    // 更新当前语言显示
    const display = document.getElementById('currentLanguageDisplay');
    if (display) {
        display.textContent = lang === 'zh' ? '简体中文' : 'Tiếng Việt (Vietnamese)';
    }

    // 更新页面所有带 data-i18n 的元素
    updatePageLanguage();
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

// ==================== 选项卡切换功能 ====================
/**
 * 切换设置模态框中的选项卡
 * @param {string} tabName - 选项卡名称 (api/language/index/other)
 */
function switchTab(tabName) {
    // 1. 隐藏所有选项卡内容
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.add('hidden');
    });

    // 2. 显示选中的选项卡内容
    const targetContent = document.getElementById(`tab-content-${tabName}`);
    if (targetContent) {
        targetContent.classList.remove('hidden');
    }

    // 3. 更新选项卡按钮样式
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.classList.remove('active', 'text-cyan-400', 'border-cyan-400');
        tab.classList.add('text-slate-400', 'border-transparent');
    });

    const activeTab = document.getElementById(`tab-${tabName}`);
    if (activeTab) {
        activeTab.classList.remove('text-slate-400', 'border-transparent');
        activeTab.classList.add('active', 'text-cyan-400', 'border-cyan-400');
    }
}
// ============================================================

// 页面加载时初始化语言
document.addEventListener('DOMContentLoaded', () => {
    setLanguage(window.currentLanguage);
});
