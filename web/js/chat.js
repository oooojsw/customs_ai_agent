// ----------------------------------------------------
// 模块 B: 咨询逻辑
// ----------------------------------------------------
// 检测用户是否正在手动滚动查看历史记录
let isUserScrolling = false;
let scrollTimeout = null;

async function sendMessage() {
    const input = document.getElementById('chatInput');
    const history = document.getElementById('chatHistory');
    const msg = input.value.trim();
    if (!msg) return;

    // User msg
    history.innerHTML += `<div class="flex justify-end"><div class="chat-bubble chat-user">${msg}</div></div>`;
    input.value = '';
    scrollToBottom(history);

    // AI thinking
    const thinkingId = 'thinking-' + Date.now();
    history.innerHTML += `<div id="${thinkingId}" class="flex justify-start"><div class="chat-thinking"><i class="fa-solid fa-spinner fa-spin"></i> ${t('thinking')}</div></div>`;
    scrollToBottom(history);

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
                        // 只有当用户不在滚动时才自动滚动
                        if (!isUserScrolling) {
                            scrollToBottom(history);
                        }
                    } else if (data.type === 'thinking') {
                        // 可以在这里更新思考状态文字，这里简单跳过
                    }
                }
            }
        }
    } catch(e) {
        document.getElementById(thinkingId).innerHTML = `${t('error')}: ` + e;
    }
}

// 智能滚动到底部函数
function scrollToBottom(element) {
    requestAnimationFrame(() => {
        element.scrollTop = element.scrollHeight;
    });
}

// 初始化滚动监听（在页面加载后调用）
function initChatScrollListener() {
    const history = document.getElementById('chatHistory');
    if (!history) return;

    history.addEventListener('scroll', () => {
        // 检测是否距离底部超过50px
        const isNearBottom = history.scrollHeight - history.scrollTop - history.clientHeight < 50;

        if (!isNearBottom) {
            isUserScrolling = true;
            // 清除之前的定时器
            if (scrollTimeout) clearTimeout(scrollTimeout);
            // 2秒后恢复自动滚动
            scrollTimeout = setTimeout(() => {
                isUserScrolling = false;
            }, 2000);
        } else {
            // 如果用户滚动回底部，立即恢复自动滚动
            isUserScrolling = false;
        }
    });
}