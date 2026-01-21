/**
 * 索引管理模块
 * 负责处理知识库索引的重建（分阶段显示）
 */

// API 配置
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : '';

// 全局状态
let isIndexRebuilding = false;

/**
 * 开始重建索引
 */
async function startRebuildIndex() {
    // 防止重复点击
    if (isIndexRebuilding) {
        console.warn('索引重建正在进行中，请勿重复点击');
        return;
    }

    const btn = document.getElementById('reindexBtn');
    const icon = document.getElementById('reindexIcon');
    const text = document.getElementById('reindexText');

    // 更新按钮状态
    isIndexRebuilding = true;
    btn.disabled = true;
    btn.className = 'w-full py-2 bg-slate-800 text-slate-500 rounded text-sm font-bold border border-slate-600 cursor-not-allowed flex items-center justify-center gap-2';
    icon.className = 'fa-solid fa-spinner fa-spin';
    text.textContent = t('rebuilding');

    // 显示文件处理区域
    document.getElementById('indexFileArea').classList.remove('hidden');
    updateCurrentFile('正在初始化...');

    try {
        // 发起 SSE 请求
        const response = await fetch(`${API_BASE_URL}/api/v1/index/rebuild`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        // 处理 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // 处理完整的 SSE 消息
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleIndexEvent(data);
                    } catch (e) {
                        console.error('解析SSE消息失败:', e, line);
                    }
                }
            }
        }

    } catch (error) {
        console.error('索引重建失败:', error);
        showErrorUI(error.message);
    } finally {
        resetUIState();
    }
}

/**
 * 处理索引重建的 SSE 事件
 */
function handleIndexEvent(data) {
    const { type, message, current_file, batch_num, total_batches, percentage, stats } = data;

    switch (type) {
        case 'init':
            updateCurrentFile('开始扫描文件...');
            break;

        case 'progress':
            // 文件处理进度 - 更新当前文件名
            if (current_file) {
                updateCurrentFile(`正在处理: ${current_file}`);
            }
            break;

        case 'step':
            // 阶段提示
            if (message) {
                updateCurrentFile(message);
            }
            break;

        case 'embedding_start':
            // 开始向量化 - 隐藏文件显示，显示进度条
            document.getElementById('indexFileArea').classList.add('hidden');
            document.getElementById('indexEmbeddingArea').classList.remove('hidden');
            updateEmbeddingProgress(0, total_batches, 0);
            break;

        case 'embedding_progress':
            // 向量化进度（批次号）
            updateEmbeddingProgress(batch_num, total_batches, percentage);
            break;

        case 'complete':
            showCompleteUI(stats);
            break;

        case 'error':
            showErrorUI(message);
            break;

        case 'cancelled':
            showCancelledUI(message);
            break;

        default:
            console.warn('未知的SSE事件类型:', type);
    }
}

/**
 * 更新当前处理文件
 */
function updateCurrentFile(text) {
    document.getElementById('indexCurrentFile').textContent = text;
}

/**
 * 更新向量化进度
 */
function updateEmbeddingProgress(batchNum, totalBatches, percentage) {
    const bar = document.getElementById('indexEmbeddingBar');
    const statusText = document.getElementById('indexEmbeddingStatus');
    const percentText = document.getElementById('indexEmbeddingPercent');

    bar.style.width = `${percentage}%`;
    statusText.textContent = `正在向量化: ${batchNum}/${totalBatches}`;
    percentText.textContent = `${percentage.toFixed(1)}%`;

    // 完成时变绿
    if (percentage >= 100) {
        bar.className = 'h-full bg-gradient-to-r from-green-500 to-emerald-500 transition-all duration-300';
    }
}

/**
 * 显示完成UI
 */
function showCompleteUI(stats) {
    // 隐藏所有处理UI
    document.getElementById('indexFileArea').classList.add('hidden');
    document.getElementById('indexEmbeddingArea').classList.add('hidden');

    // 显示完成信息
    const completeArea = document.getElementById('indexCompleteArea');
    const completeMessage = document.getElementById('indexCompleteMessage');

    let details = `${t('total_files')}: ${stats.total_files}`;
    if (stats.txt_files !== undefined) {
        details += ` (TXT: ${stats.txt_files}`;
    }
    if (stats.pdf_files !== undefined) {
        details += `, PDF: ${stats.pdf_files})`;
    }
    details += `, ${t('total_chunks')}: ${stats.total_chunks}`;

    completeMessage.textContent = `${t('index_complete')} (${details})`;
    completeMessage.className = 'text-xs text-green-400';
    completeArea.classList.remove('hidden');

    // 5秒后隐藏
    setTimeout(() => {
        completeArea.classList.add('hidden');
        // 重置进度条颜色
        const bar = document.getElementById('indexEmbeddingBar');
        bar.className = 'h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-300';
        bar.style.width = '0%';
    }, 5000);
}

/**
 * 显示错误UI
 */
function showErrorUI(message) {
    // 隐藏所有处理UI
    document.getElementById('indexFileArea').classList.add('hidden');
    document.getElementById('indexEmbeddingArea').classList.add('hidden');

    // 显示错误信息
    const completeArea = document.getElementById('indexCompleteArea');
    const completeMessage = document.getElementById('indexCompleteMessage');

    completeMessage.textContent = `${t('index_error')}: ${message}`;
    completeMessage.className = 'text-xs text-red-400';
    completeArea.classList.remove('hidden');

    // 5秒后隐藏
    setTimeout(() => {
        completeArea.classList.add('hidden');
    }, 5000);
}

/**
 * 显示取消UI
 */
function showCancelledUI(message) {
    // 隐藏所有处理UI
    document.getElementById('indexFileArea').classList.add('hidden');
    document.getElementById('indexEmbeddingArea').classList.add('hidden');

    // 显示取消信息
    const completeArea = document.getElementById('indexCompleteArea');
    const completeMessage = document.getElementById('indexCompleteMessage');

    completeMessage.textContent = message;
    completeMessage.className = 'text-xs text-yellow-400';
    completeArea.classList.remove('hidden');

    // 3秒后隐藏
    setTimeout(() => {
        completeArea.classList.add('hidden');
    }, 3000);
}

/**
 * 重置UI状态
 */
function resetUIState() {
    isIndexRebuilding = false;

    const btn = document.getElementById('reindexBtn');
    const icon = document.getElementById('reindexIcon');
    const text = document.getElementById('reindexText');

    btn.disabled = false;
    btn.className = 'w-full py-2 bg-slate-700 hover:bg-slate-600 text-cyan-400 rounded text-sm font-bold border border-slate-600 transition flex items-center justify-center gap-2';
    icon.className = 'fa-solid fa-rotate';
    text.textContent = t('rebuild_index');
}
