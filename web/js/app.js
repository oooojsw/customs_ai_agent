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