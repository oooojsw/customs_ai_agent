// ----------------------------------------------------
// 模块 B: 咨询逻辑
// ----------------------------------------------------
// 检测用户是否正在手动滚动查看历史记录
let isUserScrolling = false;
let scrollTimeout = null;

// 工具名称映射（显示名称）
function getToolDisplayName(toolName) {
    const toolNames = {
        'audit_declaration': t('tool_audit_declaration'),
        'search_customs_regulations': t('tool_search_customs_regulations')
    };
    return toolNames[toolName] || toolName;
}

// 工具结果存储（按工具索引）
const toolResults = new Map();
let toolIndex = 0;

// 切换工具结果显示
function toggleToolResult(toolIdx) {
    const resultContainer = document.getElementById(`tool-result-${toolIdx}`);
    const expandBtn = document.getElementById(`tool-expand-${toolIdx}`);

    if (resultContainer && expandBtn) {
        const isExpanded = resultContainer.classList.contains('show');

        if (isExpanded) {
            resultContainer.classList.remove('show');
            expandBtn.classList.remove('expanded');
        } else {
            resultContainer.classList.add('show');
            expandBtn.classList.add('expanded');
        }
    }
}

async function sendMessage() {
    const input = document.getElementById('chatInput');
    const history = document.getElementById('chatHistory');
    const msg = input.value.trim();
    if (!msg) return;

    // 不重置工具索引，让全局递增，确保每轮对话的ID唯一
    toolResults.clear();

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
        let currentContentBuffer = '';  // 当前累积的内容
        let lastContentDiv = null;  // 最后一个内容div

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
                        currentContentBuffer += data.content;
                        // 更新或创建内容div
                        if (lastContentDiv) {
                            lastContentDiv.innerHTML = marked.parse(currentContentBuffer);
                        } else {
                            const contentDiv = document.createElement('div');
                            contentDiv.className = 'ai-content';
                            contentDiv.innerHTML = marked.parse(currentContentBuffer);
                            document.getElementById(answerId).appendChild(contentDiv);
                            lastContentDiv = contentDiv;
                        }
                        // 只有当用户不在滚动时才自动滚动
                        if (!isUserScrolling) {
                            scrollToBottom(history);
                        }
                    } else if (data.type === 'thinking') {
                        // AI思考过程（DeepSeek R1推理流）
                        // 可以选择显示或隐藏
                    } else if (data.type === 'tool_start') {
                        // 工具调用开始 - 插入到AI回答气泡内（在文本内容之后）
                        const currentToolIdx = toolIndex++;
                        toolResults.set(currentToolIdx, ''); // 初始化结果为空

                        const toolDisplayName = getToolDisplayName(data.tool_name);
                        const toolHtml = `
                            <div class="chat-tool-status calling" data-tool-name="${data.tool_name}" data-tool-idx="${currentToolIdx}">
                                <div class="chat-tool-status-left">
                                    <i class="fa-solid fa-gear tool-icon"></i>
                                    <span class="tool-name">${toolDisplayName}</span>
                                    <span class="status-text">${t('tool_calling')}</span>
                                </div>
                                <button class="chat-tool-expand-btn" id="tool-expand-${currentToolIdx}" onclick="toggleToolResult(${currentToolIdx})" title="展开/收起工具结果">
                                    <i class="fa-solid fa-chevron-down"></i>
                                </button>
                            </div>
                            <div class="chat-tool-result" id="tool-result-${currentToolIdx}">
                                <div class="chat-tool-result-content" id="tool-result-content-${currentToolIdx}"></div>
                            </div>
                        `;
                        // 将工具状态插入到最后一个内容div之后
                        const answerElement = document.getElementById(answerId);
                        if (lastContentDiv) {
                            lastContentDiv.insertAdjacentHTML('afterend', toolHtml);
                        } else {
                            answerElement.insertAdjacentHTML('beforeend', toolHtml);
                        }

                        // 重置内容buffer，准备接收工具调用后的新内容
                        currentContentBuffer = '';
                        lastContentDiv = null;

                        if (!isUserScrolling) {
                            scrollToBottom(history);
                        }
                    } else if (data.type === 'tool_end') {
                        // 工具调用结束 - 基于工具名精确匹配查找对应的calling状态并更新
                        const answerElement = document.getElementById(answerId);
                        const toolStatusElements = answerElement.querySelectorAll('.chat-tool-status.calling');

                        // 基于工具名精确匹配（修复bug：不要依赖数组位置）
                        const targetTool = Array.from(toolStatusElements).find(
                            element => element.getAttribute('data-tool-name') === data.tool_name
                        );

                        if (targetTool) {
                            const toolIdx = targetTool.getAttribute('data-tool-idx');

                            // 移除空值检查，始终保存结果（修复bug：空结果也能展开）
                            const toolResult = data.tool_result || '';
                            toolResults.set(parseInt(toolIdx), toolResult);

                            // 始终更新结果容器内容
                            const resultContent = document.getElementById(`tool-result-content-${toolIdx}`);
                            if (resultContent) {
                                resultContent.textContent = toolResult;
                            }

                            // 更新工具状态为完成
                            const toolDisplayName = getToolDisplayName(data.tool_name);
                            targetTool.className = 'chat-tool-status done';
                            targetTool.innerHTML = `
                                <div class="chat-tool-status-left">
                                    <i class="fa-solid fa-check tool-icon"></i>
                                    <span class="tool-name">${toolDisplayName}</span>
                                    <span class="status-text">${t('tool_call_done')}</span>
                                </div>
                                <button class="chat-tool-expand-btn" id="tool-expand-${toolIdx}" onclick="toggleToolResult(${toolIdx})" title="展开/收起工具结果">
                                    <i class="fa-solid fa-chevron-down"></i>
                                </button>
                            `;

                            if (!isUserScrolling) {
                                scrollToBottom(history);
                            }
                        }
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