// ----------------------------------------------------
// 模块 C: 智能建议书 (Pro 核心)
// ----------------------------------------------------

let isProMode = false;
let reportController = null;

function importFromAudit() {
    const raw = document.getElementById('rawDataInput').value;
    const res = document.getElementById('finalResult').innerText;
    if (!raw && !res) return alert("无审单数据");
    document.getElementById('reportContextInput').value = "【报关数据】\n" + raw + "\n\n【初审结论】\n" + res;
    document.getElementById('source-status').classList.remove('hidden');
}

function toggleProMode(enable) {
    isProMode = enable;
    const layout = document.getElementById('report-layout');
    const panelBrain = document.getElementById('panel-brain');
    
    // 按钮状态切换
    document.getElementById('mode-std').className = !enable ? "px-3 py-1 rounded-full text-xs font-bold bg-slate-700 text-white shadow-inner" : "px-3 py-1 rounded-full text-xs font-bold text-slate-400 hover:text-white transition";
    document.getElementById('mode-pro').className = enable ? "px-3 py-1 rounded-full text-xs font-bold bg-indigo-600 text-white shadow-lg transition transform scale-105" : "px-3 py-1 rounded-full text-xs font-bold text-slate-400 hover:text-white transition";

    document.getElementById('btn-gen-std').classList.toggle('hidden', enable);
    document.getElementById('btn-gen-pro').classList.toggle('hidden', !enable);

    if (enable) {
        layout.className = 'layout-pro';
        panelBrain.classList.remove('hidden');
        panelBrain.classList.add('flex');
    } else {
        layout.className = 'layout-standard';
        panelBrain.classList.add('hidden');
        panelBrain.classList.remove('flex');
    }
}

async function startReport(isPro) {
    const raw = document.getElementById('reportContextInput').value;
    if (!raw.trim()) return alert("请先输入数据");

    // UI Reset
    document.getElementById(isPro ? 'btn-gen-pro' : 'btn-gen-std').disabled = true;
    document.getElementById('btn-stop').classList.remove('hidden');
    
    const contentEl = document.getElementById('reportContent');
    contentEl.innerHTML = '';
    
    const timelineEl = document.getElementById('reportTimeline');
    timelineEl.innerHTML = '<span class="text-green-400 animate-pulse"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i> 初始化中...</span>';

    // Pro UI Reset
    if (isPro) {
        document.getElementById('evidence-list').innerHTML = '';
        document.getElementById('thought-log').innerHTML = '';
    }

    // 【中断控制】创建新的控制器
    reportController = new AbortController();

    try {
        const res = await fetch(REPORT_API_URL, {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ raw_data: raw }),
            signal: reportController.signal // 绑定中断信号
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        
        // 🔥🔥🔥 关键修复：这里必须是 let，不能是 const 🔥🔥🔥
        let buffer = ''; 

        while(true) {
            const {done, value} = await reader.read();
            if(done) break;
            
            // 这里的 += 赋值操作要求 buffer 必须是变量
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n\n');
            
            // 这里的赋值操作也要求 buffer 必须是变量
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.substring(6));
                        handleReportEvent(event);
                    } catch(e) {
                        console.warn("JSON Parse Error:", e);
                    }
                }
            }
        }
    } catch(e) {
        if (e.name === 'AbortError') {
            contentEl.innerHTML += `<div class="mt-8 p-4 bg-yellow-900/20 border border-yellow-600/50 rounded-lg text-center text-yellow-500">⚠️ 用户已手动终止生成</div>`;
        } else {
            console.error(e);
            contentEl.innerHTML = `<div class="text-red-500 p-4">生成错误: ${e.message}</div>`;
        }
    } finally {
        // 清理工作
        document.getElementById('btn-stop').classList.add('hidden');
        document.getElementById(isPro ? 'btn-gen-pro' : 'btn-gen-std').disabled = false;
        reportController = null;
    }
}

function stopGeneration() {
    if (reportController) {
        reportController.abort(); // 触发中断
    }
}

function handleReportEvent(event) {
    const { type, payload } = event;
    const contentEl = document.getElementById('reportContent');

    // --- 处理 Pro 模式特有事件 ---
    if (isProMode) {
        const logEl = document.getElementById('thought-log');
        const evidenceEl = document.getElementById('evidence-list');

        if (type === 'thought') {
            const div = document.createElement('div');
            div.className = 'terminal-line';
            div.innerHTML = `<span class="terminal-timestamp">[${new Date().toLocaleTimeString().split(' ')[0]}]</span>${payload}`;
            logEl.appendChild(div);
            logEl.scrollTop = logEl.scrollHeight;
        }
        else if (type === 'rag_search') {
            const div = document.createElement('div');
            div.className = 'terminal-line text-yellow-400';
            div.innerHTML = `<span class="terminal-timestamp">[SEARCH]</span> 正在检索: "${payload.query}"`;
            logEl.appendChild(div);
            logEl.scrollTop = logEl.scrollHeight;
        }
        else if (type === 'rag_result') {
            const card = document.createElement('div');
            card.className = 'doc-card';
            card.innerHTML = `<i class="fa-solid fa-file-lines text-blue-400"></i><div class="flex-1 truncate"><div class="text-white">${payload.filename}</div><div class="text-[10px] text-slate-500">${payload.snippet}</div></div><span class="text-green-500 font-bold">${Math.floor(payload.score*100)}%</span>`;
            evidenceEl.appendChild(card);
            evidenceEl.scrollTop = evidenceEl.scrollHeight;
        }
        else if (type === 'take_note') {
            const card = document.createElement('div');
            card.className = 'note-card';
            card.innerHTML = `<i class="fa-solid fa-pen-to-square mr-1"></i> ${payload.content}`;
            evidenceEl.appendChild(card);
            evidenceEl.scrollTop = evidenceEl.scrollHeight;
        }
    }

    // --- 通用处理 ---
    if (type === 'toc') {
        document.getElementById('reportTimeline').innerHTML = payload.map((t, i) => {
            const cleanTitle = t.replace(/^\d+\.\s*/, '').replace(/\*\*/g, '');
            return `
            <div id="tl-${i}" class="px-4 py-1.5 bg-slate-700/50 border border-slate-600 rounded-full text-xs text-slate-400 opacity-60 transition flex items-center whitespace-nowrap shrink-0">
                <span class="w-4 h-4 rounded-full bg-slate-600 text-[10px] flex items-center justify-center mr-2 text-white">${i + 1}</span>
                ${cleanTitle}
            </div>`;
        }).join('');
    }
    else if (type === 'step_start') {
        contentEl.innerHTML += `<div class="mb-8"><h2 class="text-xl font-bold text-cyan-400 mb-4 border-b border-slate-700 pb-2">${payload.title}</h2><div id="curr-section" class="text-slate-300 leading-7"></div></div>`;
        const tlItem = document.getElementById(`tl-${payload.index}`);
        if (tlItem) { 
            tlItem.classList.remove('opacity-60', 'bg-slate-700/50', 'border-slate-600'); 
            tlItem.classList.add('bg-blue-600', 'border-blue-400', 'text-white', 'shadow-lg', 'scale-105'); 
            tlItem.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
        requestAnimationFrame(() => { 
            contentEl.scrollTop = contentEl.scrollHeight; 
        });
    }
    else if (type === 'report_chunk') {
        const currSection = document.getElementById('curr-section');
        if (currSection) {
            const raw = currSection.getAttribute('data-raw') || '';
            // 🔥 这里也要注意，不要写成 raw += payload，因为 raw 是 const
            const newRaw = raw + payload;
            currSection.setAttribute('data-raw', newRaw);
            currSection.innerHTML = marked.parse(newRaw);
            
            const isUserAtBottom = (contentEl.scrollHeight - contentEl.scrollTop - contentEl.clientHeight) < 150;
            if (isUserAtBottom) {
                requestAnimationFrame(() => {
                    contentEl.scrollTop = contentEl.scrollHeight;
                });
            }
        }
    }
    else if (type === 'step_done') {
            const doneSection = document.getElementById('curr-section');
            if(doneSection) doneSection.removeAttribute('id');
            
            if(isProMode) {
                const doneLog = document.createElement('div');
                doneLog.className = 'terminal-line text-green-400';
                doneLog.innerText = `>> SECTION ${payload.index} COMPLETED.`;
                document.getElementById('thought-log').appendChild(doneLog);
                const logEl = document.getElementById('thought-log');
                logEl.scrollTop = logEl.scrollHeight;
            }
    }
    else if (type === 'done') {
        contentEl.innerHTML += `<div class="mt-8 p-6 bg-green-900/20 border border-green-600/50 rounded-lg text-center"><i class="fa-solid fa-check-circle text-green-500 text-4xl mb-2"></i><h3 class="text-green-400 font-bold">审计报告生成完毕</h3></div>`;
        setTimeout(() => {
            contentEl.scrollTop = contentEl.scrollHeight;
        }, 100);
    }
}