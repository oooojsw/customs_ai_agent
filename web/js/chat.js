// ----------------------------------------------------
// 模块 B: 咨询逻辑
// ----------------------------------------------------
// 检测用户是否正在手动滚动查看历史记录
let isUserScrolling = false;
let scrollTimeout = null;

// ==================== 聊天图片上传（层次①：选图→OCR→拼 message） ====================
// 暂存用户选中的图片文件，发送时自动 OCR
let pendingChatImage = null;
let activeChatRun = null;
let chatRequestStarting = false;
let chatCancellationPending = false;

function setChatButtonState(state) {
    const sendBtn = document.getElementById('sendBtn');
    const stopBtn = document.getElementById('chatStopBtn');
    if (!sendBtn || !stopBtn) return;

    if (state === 'running' || state === 'stopping') {
        sendBtn.classList.add('hidden');
        stopBtn.classList.remove('hidden');
        stopBtn.classList.add('flex');
        stopBtn.disabled = state === 'stopping';
        stopBtn.title = state === 'stopping' ? t('chat_stopping') : t('chat_stop');
        stopBtn.innerHTML = state === 'stopping'
            ? '<i class="fa-solid fa-spinner fa-spin"></i>'
            : '<i class="fa-solid fa-stop"></i>';
    } else {
        stopBtn.classList.add('hidden');
        stopBtn.classList.remove('flex');
        stopBtn.disabled = false;
        sendBtn.classList.remove('hidden');
        sendBtn.disabled = state === 'starting';
        sendBtn.title = t('chat_send');
        sendBtn.innerHTML = state === 'starting'
            ? '<i class="fa-solid fa-spinner fa-spin"></i>'
            : '<i class="fa-solid fa-paper-plane"></i>';
    }
}

async function requestChatAgentCancellation(runId, requestId) {
    const response = await fetch(`${AGENT_RUNS_URL}/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST',
        headers: {
            'X-Request-ID': requestId,
            'X-Tenant-ID': TENANT_ID,
            'X-Service-Name': 'customs-web-demo'
        }
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error?.message || payload.detail || `HTTP ${response.status}`);
    }
    return response.json();
}

async function stopChatAgent() {
    const run = activeChatRun;
    if (!run || run.cancellationRequested) return;

    run.cancellationRequested = true;
    chatCancellationPending = true;
    if (run.streamController) run.streamController.abort();
    setChatButtonState('stopping');
    try {
        await requestChatAgentCancellation(run.runId, run.requestId);
    } catch (error) {
        console.error('[Agent V1 cancel failed]', error);
    } finally {
        chatCancellationPending = false;
        setChatButtonState('idle');
    }
}

/**
 * 聊天输入区：用户从 input[type=file] 选完图片后触发
 * 只展示预览 + 暂存文件，真正的 OCR 在 sendMessage 阶段才发请求
 */
function handleChatImageSelection(input) {
    const file = input.files && input.files[0];
    if (!file) return;

    // 大小保护：> 20MB 拒绝（与 audit 一致）
    if (file.size > 20 * 1024 * 1024) {
        alert(t('image_recognition_failed') + ' > 20MB');
        input.value = '';
        return;
    }

    pendingChatImage = file;

    const bar = document.getElementById('chatImagePreviewBar');
    const img = document.getElementById('chatImagePreviewImg');
    const name = document.getElementById('chatImagePreviewName');
    if (bar && img && name) {
        if (img._objectUrl) {
            URL.revokeObjectURL(img._objectUrl);
        }
        img._objectUrl = URL.createObjectURL(file);
        img.src = img._objectUrl;
        name.textContent = file.name;
        bar.classList.remove('hidden');
    }
}

/**
 * 取消已选图片（X 按钮）
 */
function clearChatImage() {
    pendingChatImage = null;
    const bar = document.getElementById('chatImagePreviewBar');
    const img = document.getElementById('chatImagePreviewImg');
    const input = document.getElementById('chatImageInput');
    if (img && img._objectUrl) {
        URL.revokeObjectURL(img._objectUrl);
        img._objectUrl = null;
    }
    if (img) img.src = '';
    if (input) input.value = '';
    if (bar) bar.classList.add('hidden');
}

/**
 * 调用后端 /analyze_image 拿 OCR 文本
 * 失败时抛出错误由 sendMessage 兜底
 * 【关键】加 15s AbortController 超时：后端转发到慢上游时会卡 120s，前端不能跟它一起死
 */
async function ocrChatImage(file) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('language', window.currentLanguage || 'zh');

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);  // 15s 超时

    let response;
    try {
        response = await fetch(IMAGE_API_URL, {
            method: 'POST',
            body: fd,
            signal: controller.signal
        });
    } catch (e) {
        clearTimeout(timeoutId);
        if (e.name === 'AbortError') {
            throw new Error('OCR 服务响应超时（>15s），请稍后重试');
        }
        throw e;
    }
    clearTimeout(timeoutId);

    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || t('recognition_error'));
    }
    const json = await response.json();
    return (json && (json.text || json.content || json.context)) || '';
}

// 工具名称映射（显示名称）
function getToolDisplayName(toolName) {
    const toolNames = {
        'audit_declaration': t('tool_audit_declaration'),
        'search_customs_regulations': t('tool_search_customs_regulations'),
        'invoke_skill': '执行技能插件 (Skill Execution)'
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

function createAgentRequestId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return `web-${window.crypto.randomUUID()}`;
    }
    return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function createChatAgentRun(message) {
    const requestId = createAgentRequestId();
    const response = await fetch(AGENT_RUNS_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Request-ID': requestId,
            'X-Tenant-ID': TENANT_ID,
            'X-Service-Name': 'customs-web-demo'
        },
        body: JSON.stringify({
            request_id: requestId,
            session: {
                session_id: SESSION_ID,
                user_id: USER_ID,
                tenant_id: TENANT_ID
            },
            message: {
                role: 'user',
                content: message
            },
            language: window.currentLanguage || 'zh',
            attachments: [],
            business_context: {},
            options: {
                intent: 'auto',
                response_mode: 'stream',
                include_tool_trace: true,
                include_structured_result: true,
                output_file_policy: 'agent_temporary',
                timeout_seconds: 600
            }
        })
    });

    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const messageText = payload.error?.message || payload.detail || `HTTP ${response.status}`;
        throw new Error(messageText);
    }
    return response.json();
}

function parseAgentSseBlock(block) {
    const dataLines = block
        .split('\n')
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trimStart());
    if (!dataLines.length) return null;
    return JSON.parse(dataLines.join('\n'));
}

function mapAgentEventToLegacyEvent(envelope) {
    const eventData = envelope.data || {};
    switch (envelope.event) {
        case 'message_delta':
            return { type: 'answer', content: eventData.content || '' };
        case 'tool_started':
            return {
                type: 'tool_start',
                tool_name: eventData.tool || 'unknown_tool',
                display_name: eventData.display_name
            };
        case 'tool_finished':
            return {
                type: 'tool_end',
                tool_name: eventData.tool || 'unknown_tool',
                tool_result: eventData.summary || ''
            };
        case 'output_created':
            return { type: 'output_created', output: eventData.output || eventData };
        case 'warning':
            return { type: 'warning', error: eventData.error || eventData };
        case 'agent_failed':
            return { type: 'error', error: eventData.error || {} };
        case 'agent_cancelled':
            return { type: 'cancelled' };
        case 'agent_completed':
            return { type: 'done', result: eventData };
        default:
            return null;
    }
}

function appendAgentOutput(answerElement, output) {
    if (!output) return;
    const downloadUrl = output.download_url || output.agent_output_url;
    if (!downloadUrl) return;

    const container = document.createElement('div');
    container.className = 'download-button-container';

    const link = document.createElement('a');
    link.href = downloadUrl;
    link.className = 'download-button';
    link.download = output.name || '';

    const icon = document.createElement('i');
    icon.className = output.kind === 'image'
        ? 'fa-solid fa-image'
        : 'fa-solid fa-file-arrow-down';

    const label = document.createElement('span');
    label.textContent = output.name || t('download_word');

    link.appendChild(icon);
    link.appendChild(label);
    container.appendChild(link);
    answerElement.appendChild(container);
}

async function sendMessage() {
    const input = document.getElementById('chatInput');
    const history = document.getElementById('chatHistory');
    const sendBtn = document.getElementById('sendBtn');
    const imageBtn = document.getElementById('chatImageBtn');
    if (activeChatRun || chatRequestStarting || chatCancellationPending) return;
    chatRequestStarting = true;
    setChatButtonState('starting');

    let msg = input.value.trim();
    if (!msg && !pendingChatImage) {
        chatRequestStarting = false;
        setChatButtonState('idle');
        return;
    }
    const originalUserMsg = msg;
    const hadChatImage = !!pendingChatImage;

    // 不重置工具索引，让全局递增，确保每轮对话的ID唯一
    toolResults.clear();

    // ============ 层次①：有挂起图片时，先 OCR 再拼 message ============
    let ocrText = '';
    let ocrFailed = false;
    if (pendingChatImage) {
        // 锁住发送按钮 + 切换到"识别中"状态
        sendBtn.disabled = true;
        if (imageBtn) imageBtn.disabled = true;
        const originalSendHtml = sendBtn.innerHTML;
        sendBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
        try {
            ocrText = await ocrChatImage(pendingChatImage);
            if (!ocrText) {
                console.warn('[chat OCR empty]', t('chat_ocr_empty'));
                ocrFailed = true;
            }
        } catch (e) {
            console.error('[chat OCR failed]', e);
            ocrFailed = true;
            // OCR 失败：图片留在预览条让用户重试/移除，释放按钮让原文字消息照发
            // 改用 console.error 而非 alert() — alert 是同步阻塞，会卡住后续代码
        } finally {
            sendBtn.disabled = false;
            if (imageBtn) imageBtn.disabled = false;
            sendBtn.innerHTML = originalSendHtml;
        }
        // OCR 成功：清掉预览条 + 释放按钮
        if (ocrText) {
            clearChatImage();
        }
    }

    // 构造最终 message：原文本 + （可选）OCR 文本块
    const ocrPrompt = t('chat_ocr_prompt_zh');
    if (ocrText) {
        if (msg) {
            msg = `${msg}\n\n${ocrPrompt}\n${ocrText}`;
        } else {
            msg = `${ocrPrompt}\n${ocrText}`;
        }
    }

    // OCR 失败时，在消息末尾追加一个轻量提示（让 Agent 也知道图没识别成功）
    if (ocrFailed && pendingChatImage) {
        const note = `[注意：用户上传了一张图片，但 OCR 识别服务暂不可用（图片未解析成功）。请基于用户输入的文字继续回答，必要时提示用户稍后重试。]`;
        msg = msg ? `${msg}\n\n${note}` : note;
    }

    // OCR 失败时给一个非阻塞的轻量 toast 提示（不阻断 JS）
    if (ocrFailed) {
        try {
            const toast = document.createElement('div');
            toast.style.cssText = 'position:fixed;top:80px;right:20px;background:#7f1d1d;color:#fff;padding:10px 16px;border-radius:6px;z-index:9999;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
            toast.textContent = t('image_recognition_failed') + '（图片保留在预览条可重试）';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 5000);
        } catch (_) {}
    }

    // User msg（气泡里展示的是用户原本输入 + 一个图片小角标）
    const escapeHtml = (value) => value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    const userBubbleLines = (originalUserMsg || msg)
        .split('\n')
        .filter(line => line.length > 0)
        .map(line => `<div>${escapeHtml(line)}</div>`)
        .join('');
    const attachedTag = hadChatImage
        ? `<div class="text-[10px] text-cyan-300 mt-1 mb-1"><i class="fa-solid fa-image"></i> ${escapeHtml(t('chat_ocr_attached_tag'))}</div>`
        : '';
    let userBubbleHtml = `${userBubbleLines}${attachedTag}`;
    history.innerHTML += `<div class="flex justify-end"><div class="chat-bubble chat-user">${userBubbleHtml}</div></div>`;
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
        const run = await createChatAgentRun(msg);
        const streamController = new AbortController();
        activeChatRun = {
            runId: run.run_id,
            requestId: run.request_id,
            cancellationRequested: false,
            streamController
        };
        chatRequestStarting = false;
        setChatButtonState('running');
        const eventsUrl = new URL(run.events_url, AGENT_V1_BASE_URL).toString();
        const res = await fetch(eventsUrl, {
            method: 'GET',
            signal: streamController.signal,
            headers: {
                'Accept': 'text/event-stream',
                'X-Request-ID': run.request_id,
                'X-Tenant-ID': TENANT_ID,
                'X-Service-Name': 'customs-web-demo'
            }
        });

        if (!res.ok) {
            const payload = await res.json().catch(() => ({}));
            const messageText = payload.error?.message || payload.detail || `HTTP ${res.status}`;
            throw new Error(messageText);
        }
        if (!res.body) {
            throw new Error('浏览器未收到智能体事件流');
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let currentContentBuffer = '';  // 当前累积的内容
        let lastContentDiv = null;  // 最后一个内容div
        let hasDisplayedAnswer = false;

        while(true) {
            const {done, value} = await reader.read();
            if(done) break;
            buffer += decoder.decode(value, {stream: true});
            const blocks = buffer.split('\n\n');
            buffer = blocks.pop();

            for (const block of blocks) {
                const envelope = parseAgentSseBlock(block);
                if (envelope) {
                    const data = mapAgentEventToLegacyEvent(envelope);
                    if (!data) continue;

                    // 隐藏思考状态
                    document.getElementById(thinkingId).style.display = 'none';
                    answerDiv.classList.remove('hidden');

                    if (data.type === 'answer') {
                        // 🔥 过滤工具相关的废话
                        const content = data.content;

                        // 检查是否是工具调用前后的废话
                        const wastePatterns = [
                            /^(好的|我来|现在|让我|正在|开始|马上)/,  // 工具调用前
                            /^(工具|已|完成|完毕|返回)/,               // 工具调用后
                            /报告.*生成|文档.*导出|深度.*研究/         // 工具相关关键词
                        ];

                        const isWaste = wastePatterns.some(pattern => pattern.test(content.trim()));

                        // 如果是废话，不显示；否则正常显示
                        if (!isWaste) {
                            hasDisplayedAnswer = true;
                            currentContentBuffer += content;
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
                        }
                    } else if (data.type === 'thinking') {
                        // AI思考过程（DeepSeek R1推理流）
                        // 可以选择显示或隐藏
                    } else if (data.type === 'tool_start') {
                        // 工具调用开始 - 插入到AI回答气泡内（在文本内容之后）
                        const currentToolIdx = toolIndex++;
                        toolResults.set(currentToolIdx, ''); // 初始化结果为空

                        const toolDisplayName = getToolDisplayName(data.tool_name);

                        // 检查是否有 display_config
                        const hasDisplayConfig = data.display_config && data.display_config.title;

                        // 如果有 display_config，先创建 ToolOverlay
                        if (hasDisplayConfig) {
                            const overlayId = `tool-overlay-${currentToolIdx}`;
                            const showProgress = data.display_config.show_progress;
                            const animationClass = data.display_config.animation || 'fade';
                            const progressBarHtml = showProgress ? '<div class="progress-bar-mini"></div>' : '';

                            const overlayHtml = `
                                <div class="tool-overlay ${animationClass}" id="${overlayId}">
                                    <i class="fa-solid fa-spinner fa-spin"></i>
                                    <span style="margin-left: 8px;">${data.display_config.title}</span>
                                    ${progressBarHtml}
                                </div>
                            `;

                            // 将 overlay 插入到最后一个内容div之后
                            const answerElement = document.getElementById(answerId);
                            if (lastContentDiv) {
                                lastContentDiv.insertAdjacentHTML('afterend', overlayHtml);
                            } else {
                                answerElement.insertAdjacentHTML('beforeend', overlayHtml);
                            }
                        }

                        // 然后创建常规工具状态卡片
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

                            // 移除 ToolOverlay（如果存在）
                            const overlay = document.getElementById(`tool-overlay-${toolIdx}`);
                            if (overlay) {
                                // 添加淡出动画
                                overlay.style.transition = 'opacity 0.3s ease-out, transform 0.3s ease-out';
                                overlay.style.opacity = '0';
                                overlay.style.transform = 'translateY(-10px)';

                                // 动画完成后移除元素
                                setTimeout(() => {
                                    overlay.remove();
                                }, 300);
                            }

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

                            // ✨ 特殊处理：export_document_file 工具完成后添加下载按钮
                            if (data.tool_name === 'export_document_file' && toolResult) {
                                // 从工具结果中提取文件名
                                const filenameMatch = toolResult.match(/\/downloads\/([a-zA-Z0-9_\-\.]+\.docx)/);
                                if (filenameMatch) {
                                    const filename = filenameMatch[1];
                                    const downloadUrl = `/downloads/${filename}`;

                                    // 创建下载按钮
                                    const downloadBtn = document.createElement('div');
                                    downloadBtn.className = 'download-button-container';
                                    downloadBtn.innerHTML = `
                                        <a href="${downloadUrl}" download="${filename}" class="download-button">
                                            <i class="fa-solid fa-file-word"></i>
                                            <span>${t('download_word')}</span>
                                            <span class="filename">${filename}</span>
                                        </a>
                                    `;

                                    // 插入到 AI 消息的最后
                                    answerElement.appendChild(downloadBtn);
                                }
                            }

                            if (!isUserScrolling) {
                                scrollToBottom(history);
                            }
                        }
                    } else if (data.type === 'output_created') {
                        appendAgentOutput(document.getElementById(answerId), data.output);
                        if (!isUserScrolling) {
                            scrollToBottom(history);
                        }
                    } else if (data.type === 'warning') {
                        console.warn('[Agent V1 warning]', data.error);
                    } else if (data.type === 'error') {
                        throw new Error(data.error.message || t('error'));
                    } else if (data.type === 'cancelled') {
                        const answerElement = document.getElementById(answerId);
                        const cancelledDiv = document.createElement('div');
                        cancelledDiv.className = 'ai-content text-slate-400';
                        cancelledDiv.textContent = t('chat_cancelled');
                        answerElement.appendChild(cancelledDiv);
                        answerElement.querySelectorAll('.chat-tool-status.calling').forEach(element => {
                            element.classList.remove('calling');
                            element.classList.add('cancelled');
                        });
                    } else if (data.type === 'done') {
                        const finalAnswer = data.result?.final_answer || '';
                        if (!hasDisplayedAnswer && finalAnswer) {
                            const contentDiv = document.createElement('div');
                            contentDiv.className = 'ai-content';
                            contentDiv.innerHTML = marked.parse(finalAnswer);
                            document.getElementById(answerId).appendChild(contentDiv);
                            hasDisplayedAnswer = true;
                        }
                    }
                }
            }
        }
    } catch(e) {
        const thinkingElement = document.getElementById(thinkingId);
        if (e.name === 'AbortError' || activeChatRun?.cancellationRequested) {
            thinkingElement.style.display = 'none';
            answerDiv.classList.remove('hidden');
            const cancelledDiv = document.createElement('div');
            cancelledDiv.className = 'ai-content text-slate-400';
            cancelledDiv.textContent = t('chat_cancelled');
            document.getElementById(answerId).appendChild(cancelledDiv);
        } else {
            thinkingElement.style.display = '';
            thinkingElement.innerHTML = `${t('error')}: ${e.message || e}`;
        }
    } finally {
        chatRequestStarting = false;
        activeChatRun = null;
        if (!chatCancellationPending) setChatButtonState('idle');
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
