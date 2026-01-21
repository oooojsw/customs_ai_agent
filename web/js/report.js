// ----------------------------------------------------
// 模块 C: 智能建议书 (Pro 核心 - 满血修复版)
// ----------------------------------------------------

let isProMode = false;
let reportController = null;

function importFromAudit() {
    const raw = document.getElementById('rawDataInput').value;
    const res = document.getElementById('finalResult').innerText;
    if (!raw && !res) return alert(t('no_audit_data'));
    document.getElementById('reportContextInput').value = `${t('custom_data_label')}\n` + raw + `\n\n${t('preliminary_conclusion_label')}\n` + res;
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
    if (!raw.trim()) return alert(t('please_input_data_first'));

    // UI Reset
    document.getElementById(isPro ? 'btn-gen-pro' : 'btn-gen-std').disabled = true;
    document.getElementById('btn-stop').classList.remove('hidden');

    const contentEl = document.getElementById('reportContent');
    contentEl.innerHTML = '';

    const timelineEl = document.getElementById('reportTimeline');
    timelineEl.innerHTML = `<span class="text-green-400 animate-pulse"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i> ${t('connecting_brain')}...</span>`;

    // Pro UI Reset
    if (isPro) {
        document.getElementById('evidence-list').innerHTML = '';
        document.getElementById('thought-log').innerHTML = '';
    }

    reportController = new AbortController();

    try {
        // 在 fetch 之前打印
        const requestBody = JSON.stringify({ raw_data: raw, language: window.currentLanguage });
        console.log("准备发送数据:", requestBody); // <--- 加这行

        const res = await fetch(REPORT_API_URL, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: requestBody, // <--- 使用变量
            signal: reportController.signal
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = ''; 

        while(true) {
            const {done, value} = await reader.read();
            if(done) break;
            
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n\n');
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
            contentEl.innerHTML += `<div class="mt-8 p-4 bg-yellow-900/20 border border-yellow-600/50 rounded-lg text-center text-yellow-500">⚠️ ${t('user_terminated')}</div>`;
        } else {
            console.error(e);
            contentEl.innerHTML = `<div class="text-red-500 p-4">${t('generation_error')}: ${e.message}</div>`;
        }
    } finally {
        document.getElementById('btn-stop').classList.add('hidden');
        document.getElementById(isPro ? 'btn-gen-pro' : 'btn-gen-std').disabled = false;
        reportController = null;
    }
}

function stopGeneration() {
    if (reportController) {
        reportController.abort();
    }
}

function handleReportEvent(event) {
    const { type, payload } = event;
    const contentEl = document.getElementById('reportContent');

    // ✅ 新增错误处理
    if (type === 'error') {
        console.error("Backend Error:", payload);
        contentEl.innerHTML += `
            <div class="mt-4 p-4 bg-red-900/30 border border-red-500 rounded-lg animate-pulse">
                <h3 class="text-red-400 font-bold"><i class="fa-solid fa-bug"></i> ${t('generation_interrupted')}</h3>
                <p class="text-xs text-red-200 mt-1 font-mono">${payload}</p>
            </div>
        `;
        return;
    }

    // --- 处理 Pro 模式特有事件 (炫酷效果) ---
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
            div.innerHTML = `<span class="terminal-timestamp">[SEARCH]</span> ${t('searching')}: "${payload.query}"`;
            logEl.appendChild(div);
            logEl.scrollTop = logEl.scrollHeight;
        }
        else if (type === 'rag_result') {
            console.log('收到 rag_result 事件'); // 调试
            console.log('payload:', payload); // 调试
            console.log('evidenceEl:', evidenceEl); // 调试

            const card = document.createElement('div');
            card.className = 'doc-card';

            // 创建头部元素
            const header = document.createElement('div');
            header.className = 'rag-result-header cursor-pointer flex items-center gap-2 w-full';
            header.style.cursor = 'pointer'; // 确保可以点击
            header.innerHTML = `
                <i class="fa-solid fa-file-lines text-blue-400"></i>
                <div class="flex-1 truncate">
                    <div class="text-white">${payload.filename}</div>
                    <div class="text-[10px] text-slate-500">${payload.snippet.substring(0, 50)}${payload.snippet.length > 50 ? '...' : ''}</div>
                </div>
                <span class="text-green-500 font-bold">${Math.floor(payload.score*100)}%</span>
                <i class="fa-solid fa-chevron-right chevron-icon text-xs text-slate-400"></i>
            `;

            // 创建内容区域
            const content = document.createElement('div');
            content.className = 'rag-content hidden mt-3 pt-3 border-t border-slate-600 text-xs text-slate-300';

            // 直接显示 RAG 检索到的片段，而不是加载完整文件
            content.innerHTML = `
                <div class="mb-3">
                    <div class="text-xs text-cyan-400 mb-2">
                        <i class="fa-solid fa-magnifying-glass mr-1"></i>
                        RAG 检索匹配内容：
                    </div>
                    <div class="whitespace-pre-wrap font-mono text-xs leading-relaxed bg-slate-900/50 p-3 rounded border border-slate-700">
                        ${payload.snippet}
                    </div>
                </div>
                <button class="view-full-file-btn text-xs text-blue-400 hover:text-blue-300 underline">
                    <i class="fa-solid fa-file-lines mr-1"></i>
                    查看完整文件
                </button>
            `;

            // 获取箭头元素
            const chevron = header.querySelector('.chevron-icon');

            // 绑定点击事件（展开/收起）
            header.onclick = async (e) => {
                e.preventDefault();
                e.stopPropagation();

                const isHidden = content.classList.contains('hidden');

                if (isHidden) {
                    content.classList.remove('hidden');
                    chevron.style.transform = 'rotate(90deg)';
                } else {
                    content.classList.add('hidden');
                    chevron.style.transform = 'rotate(0deg)';
                }
            };

            // 绑定"查看完整文件"按钮事件
            const viewFullBtn = content.querySelector('.view-full-file-btn');
            if (viewFullBtn) {
                viewFullBtn.onclick = async (e) => {
                    e.preventDefault();
                    e.stopPropagation();

                    // 显示加载动画
                    viewFullBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i>加载中...';

                    try {
                        const fullContent = await loadRagContentForReport(payload.filename);

                        // 替换按钮为完整文件内容
                        viewFullBtn.parentElement.innerHTML = `
                            <div class="mt-3 pt-3 border-t border-slate-600">
                                <div class="text-xs text-yellow-400 mb-2">
                                    <i class="fa-solid fa-file-lines mr-1"></i>
                                    完整文件内容：
                                </div>
                                <div class="whitespace-pre-wrap font-mono text-xs leading-relaxed bg-slate-900/50 p-3 rounded border border-slate-700 max-h-96 overflow-y-auto">
                                    ${fullContent}
                                </div>
                            </div>
                        `;
                    } catch (error) {
                        viewFullBtn.innerHTML = `<span class="text-red-400">加载失败</span>`;
                        console.error('加载完整文件失败:', error);
                    }
                };
            }

            // 组装卡片
            card.appendChild(header);
            card.appendChild(content);

            evidenceEl.appendChild(card);
            evidenceEl.scrollTop = evidenceEl.scrollHeight;

            console.log('证据卡片已添加到 DOM，文件名:', payload.filename);
        }
        else if (type === 'take_note') {
            const card = document.createElement('div');
            card.className = 'note-card';
            card.innerHTML = `<i class="fa-solid fa-pen-to-square mr-1"></i> ${payload.content}`;
            evidenceEl.appendChild(card);
            evidenceEl.scrollTop = evidenceEl.scrollHeight;
        }
        else if (type === 'research_decision') {
            const { round, decision, reason, source, confidence, metrics } = payload;
            const logEl = document.getElementById('thought-log');

            const decisionDiv = document.createElement('div');

            // 根据 source 和 decision 显示不同样式
            const isAI = source === 'ai';
            const bgColor = decision === 'stop'
                ? (isAI ? 'bg-purple-900/30 border-purple-600' : 'bg-red-900/30 border-red-600')
                : (isAI ? 'bg-blue-900/30 border-blue-600' : 'bg-yellow-900/30 border-yellow-600');

            const icon = decision === 'stop' ? 'fa-stop-circle' : 'fa-arrow-right';
            const sourceBadge = isAI
                ? '<span class="text-xs bg-purple-700 px-1 rounded ml-1">AI</span>'
                : '<span class="text-xs bg-gray-600 px-1 rounded ml-1">规则</span>';

            decisionDiv.className = `terminal-line ${bgColor} border rounded px-2 py-1 mb-2`;
            decisionDiv.innerHTML = `
                <span class="terminal-timestamp">[DECISION Round ${round}]</span>
                ${sourceBadge}
                <i class="fa-solid ${icon}"></i>
                <span class="font-bold">${decision === 'stop' ? '停止检索' : '继续检索'}</span>
                ${isAI ? `<span class="text-xs text-slate-400 ml-1">置信度: ${(confidence * 100).toFixed(0)}%</span>` : ''}
                <div class="text-slate-300 text-xs mt-1">${reason}</div>
                <div class="mt-1 text-xs text-slate-500">
                    质量: ${(metrics.total_quality * 100).toFixed(0)}% |
                    相似度: ${(metrics.score * 100).toFixed(0)}% |
                    丰富度: ${(metrics.richness * 100).toFixed(0)}% |
                    去重: ${(metrics.dedup * 100).toFixed(0)}%
                </div>
            `;

            logEl.appendChild(decisionDiv);
            logEl.scrollTop = logEl.scrollHeight;
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
        
        // v3.0 的 Timeline 高亮效果
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
        contentEl.innerHTML += `<div class="mt-8 p-6 bg-green-900/20 border border-green-600/50 rounded-lg text-center"><i class="fa-solid fa-check-circle text-green-500 text-4xl mb-2"></i><h3 class="text-green-400 font-bold">${t('report_completed')}</h3></div>`;
        setTimeout(() => {
            contentEl.scrollTop = contentEl.scrollHeight;
        }, 100);
    }
}

// RAG 文件内容缓存
const ragFileContents = {
    // 基础要素完整性校验 - 多种可能的文件名
    '基础要素完整性校验.txt': `【基础要素完整性校验 - 审查指导文件】

审查要点：
1. 必填要素检查：
   - 货物名称：必须具体明确，不能使用模糊词汇如"配件"、"零件"等
   - 型号规格：必须提供具体型号、零件编号、技术参数
   - 功能用途：说明具体用途和工作原理
   - 品牌信息：明确标注品牌名称

2. 高科技商品特殊要求：
   - IC 芯片：需提供芯片型号、封装类型、制程工艺
   - 机械设备：需提供详细技术规格、功率、精度等参数
   - 电子元件：需提供电压、电流、接口类型等

3. 风险判定标准：
   - 低风险：提供完整具体的技术参数和说明
   - 高风险：仅有模糊描述，无法判断具体规格
   - 拒绝：明显虚假或缺失关键要素

4. 常见问题：
   - 货物名称过于笼统
   - 技术参数缺失或不明确
   - 功能描述简单，无法确定实际用途`,
    'rag_r01_basic_info.txt': `【基础要素完整性校验 - 审查指导文件】

审查要点：
1. 必填要素检查：
   - 货物名称：必须具体明确，不能使用模糊词汇如"配件"、"零件"等
   - 型号规格：必须提供具体型号、零件编号、技术参数
   - 功能用途：说明具体用途和工作原理
   - 品牌信息：明确标注品牌名称

2. 高科技商品特殊要求：
   - IC 芯片：需提供芯片型号、封装类型、制程工艺
   - 机械设备：需提供详细技术规格、功率、精度等参数
   - 电子元件：需提供电压、电流、接口类型等

3. 风险判定标准：
   - 低风险：提供完整具体的技术参数和说明
   - 高风险：仅有模糊描述，无法判断具体规格
   - 拒绝：明显虚假或缺失关键要素

4. 常见问题：
   - 货物名称过于笼统
   - 技术参数缺失或不明确
   - 功能描述简单，无法确定实际用途`,

    // 禁限与敏感货物筛查 - 多种可能的文件名
    '禁限与敏感货物筛查.txt': `【禁限与敏感货物筛查 - 审查指导文件】

审查要点：
1. 固体废物（洋垃圾）筛查：
   - 废旧电器：明显使用痕迹、老化严重
   - 废金属：锈蚀严重、夹杂杂质
   - 废塑料：回收标记、颜色不均
   - 报关单备注显示"二手"、"再生"、"回收"

2. 濒危物种保护：
   - 红木类：巴西玫瑰木、非洲紫檀等
   - 野生动物制品：皮革、骨头、角制品
   - 海产品：珊瑚、玳瑁制品
   - 需检查是否有 CITES 证明

3. 两用物项管控：
   - 高性能计算机：超算、服务器
   - 精密仪器：激光设备、测量仪器
   - 特殊材料：碳纤维、稀有金属
   - 检查是否需出口许可证

4. 敏感关键词：
   - "废"、"旧"、"再生"、"回收"
   - "濒危"、"保护"、"禁止"
   - "两用"、"战略"、"管制"

5. 风险判定：
   - 直接命中关键词：高风险
   - 特征明显：高风险
   - 信息不完整：中风险
   - 需进一步核实：转人工查验`,
    'rag_r02_sensitive_goods.txt': `【禁限与敏感货物筛查 - 审查指导文件】

审查要点：
1. 固体废物（洋垃圾）筛查：
   - 废旧电器：明显使用痕迹、老化严重
   - 废金属：锈蚀严重、夹杂杂质
   - 废塑料：回收标记、颜色不均
   - 报关单备注显示"二手"、"再生"、"回收"

2. 濒危物种保护：
   - 红木类：巴西玫瑰木、非洲紫檀等
   - 野生动物制品：皮革、骨头、角制品
   - 海产品：珊瑚、玳瑁制品
   - 需检查是否有 CITES 证明

3. 两用物项管控：
   - 高性能计算机：超算、服务器
   - 精密仪器：激光设备、测量仪器
   - 特殊材料：碳纤维、稀有金属
   - 检查是否需出口许可证

4. 敏感关键词：
   - "废"、"旧"、"再生"、"回收"
   - "濒危"、"保护"、"禁止"
   - "两用"、"战略"、"管制"

5. 风险判定：
   - 直接命中关键词：高风险
   - 特征明显：高风险
   - 信息不完整：中风险
   - 需进一步核实：转人工查验`,

    // 价格真实性逻辑研判 - 多种可能的文件名
    '价格真实性逻辑研判.txt': `【价格真实性逻辑研判 - 审查指导文件】

审查要点：
1. 价格合理性分析：
   - 市场价参考：查询同类商品近期价格
   - 汇率影响：考虑国际汇率波动
   - 贸易条款：FOB、CIF 等价格构成
   - 批量折扣：大额订单应有价格优惠

2. 低报价格特征：
   - 单价明显低于市场价 30% 以上
   - 同一批次价格差异过大
   - 频次申报接近监管临界值
   - 申报价格与发票不一致

3. 高报价格特征：
   - 单价明显高于市场正常水平
   - 价值申报过高影响关税收入
   - 可能涉及退税异常

4. 特殊商品价格判断：
   - 二手商品：需有折旧说明
   - 样品：通常价格为零或很低
   - 定制产品：需提供成本构成
   - 旧货残次品：需有贬值说明

5. 辅助判断工具：
   - 海关价格数据库
   - 行业价格指数
   - 企业历史价格记录
   - 第三方价格评估

6. 风险等级判定：
   - 低风险：价格合理，有合理解释
   - 中风险：价格轻微异常，需说明
   - 高风险：价格严重异常，无合理解释`,
    'rag_r03_price_logic.txt': `【价格真实性逻辑研判 - 审查指导文件】

审查要点：
1. 价格合理性分析：
   - 市场价参考：查询同类商品近期价格
   - 汇率影响：考虑国际汇率波动
   - 贸易条款：FOB、CIF 等价格构成
   - 批量折扣：大额订单应有价格优惠

2. 低报价格特征：
   - 单价明显低于市场价 30% 以上
   - 同一批次价格差异过大
   - 频次申报接近监管临界值
   - 申报价格与发票不一致

3. 高报价格特征：
   - 单价明显高于市场正常水平
   - 价值申报过高影响关税收入
   - 可能涉及退税异常

4. 特殊商品价格判断：
   - 二手商品：需有折旧说明
   - 样品：通常价格为零或很低
   - 定制产品：需提供成本构成
   - 旧货残次品：需有贬值说明

5. 辅助判断工具：
   - 海关价格数据库
   - 行业价格指数
   - 企业历史价格记录
   - 第三方价格评估

6. 风险等级判定：
   - 低风险：价格合理，有合理解释
   - 中风险：价格轻微异常，需说明
   - 高风险：价格严重异常，无合理解释`
};

// 加载 RAG 文件内容
async function loadRagContentForReport(filename) {
    console.log('loadRagContentForReport 被调用，文件名:', filename);

    try {
        // 调用后端 API 获取文件内容
        const apiUrl = `/api/v1/knowledge/content/${encodeURIComponent(filename)}`;
        console.log('请求 API:', apiUrl);

        const response = await fetch(apiUrl);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('API 响应:', data);

        if (data.status === 'success') {
            return data.content;
        } else {
            // 文件未找到或其他错误
            return data.content || `${t('no_file_content')}\n\n文件名: ${filename}`;
        }

    } catch (error) {
        console.error('加载 RAG 内容失败:', error);
        return `${t('load_file_failed')}\n\n错误: ${error.message}\n\n文件名: ${filename}`;
    }
}