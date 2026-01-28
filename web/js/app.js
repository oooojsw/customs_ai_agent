// ----------------------------------------------------
// 公共：模块切换
// ----------------------------------------------------
function switchModule(id) {
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

// ----------------------------------------------------
// 页面初始化
// ----------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    // 初始化聊天滚动监听器
    if (typeof initChatScrollListener === 'function') {
        initChatScrollListener();
    }
});