// ----------------------------------------------------
// 模块 B: 咨询逻辑
// ----------------------------------------------------
async function sendMessage() {
    const input = document.getElementById('chatInput');
    const history = document.getElementById('chatHistory');
    const msg = input.value.trim();
    if (!msg) return;

    // User msg
    history.innerHTML += `<div class="flex justify-end"><div class="chat-bubble chat-user">${msg}</div></div>`;
    input.value = '';
    history.scrollTop = history.scrollHeight;

    // AI thinking
    const thinkingId = 'thinking-' + Date.now();
    history.innerHTML += `<div id="${thinkingId}" class="flex justify-start"><div class="chat-thinking"><i class="fa-solid fa-spinner fa-spin"></i> ${t('thinking')}</div></div>`;
    history.scrollTop = history.scrollHeight;

    // AI Answer container
    const answerId = 'ai-' + Date.now();
    const answerDiv = document.createElement('div');
    answerDiv.className = 'flex justify-start hidden';
    answerDiv.innerHTML = `<div id="${answerId}" class="chat-bubble chat-ai"></div>`;
    history.appendChild(answerDiv);

    try {
        const res = await fetch(CHAT_URL, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message: msg, session_id: SESSION_ID, language: window.currentLanguage })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';

        while(true) {
            const {done, value} = await reader.read();
            if(done) break;
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));
                    
                    // 隐藏思考状态
                    document.getElementById(thinkingId).style.display = 'none';
                    answerDiv.classList.remove('hidden');

                    if (data.type === 'answer') {
                        fullText += data.content;
                        document.getElementById(answerId).innerHTML = marked.parse(fullText);
                    } else if (data.type === 'thinking') {
                        // 可以在这里更新思考状态文字，这里简单跳过
                    }
                    history.scrollTop = history.scrollHeight;
                }
            }
        }
    } catch(e) {
        document.getElementById(thinkingId).innerHTML = `${t('error')}: ` + e;
    }
}