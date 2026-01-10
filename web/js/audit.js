// ----------------------------------------------------
// 模块 A: 审单逻辑 (已补全所有案例)
// ----------------------------------------------------
const SAMPLES = {
    sample10: `报关单号：TEST-010\n货物名称：全自动贴片机\nHS编码：84798962\n数量：1 台\n单价：150,000.00 USD\n总价：150,000.00 USD\n毛重：1200.0 KG\n净重：1150.0 KG\n品牌：Panasonic\n申报要素：\n  1.品名：全自动贴片机；\n  2.品牌：Panasonic；\n  3.型号：NPM-D3A；\n  4.功能：用于PCB电路板元件贴装；\n  5.原理：通过吸嘴吸取元件放置于PCB板。\n【随附单证信息】\n发票 INV-998877:\n   - 金额：150,000.00 USD\n装箱单 PL-998877:\n   - 毛重：1200.0 KG\n   - 净重：1150.0 KG`,
    sample1: `报关单号：TEST-001\n货物名称：DJI Mavic 3 Pro 航拍飞行器\nHS编码：95030039 (其他缩微模型/玩具)\n数量：100台\n单价：1800.00 USD\n总价：180000.00 USD\n申报要素：1.品名：航拍飞行器；2.材质：塑料；3.品牌：DJI；4.型号：Mavic 3 Pro。\n【随附单证】\n发票总额：180,000 USD`,
    sample2: `报关单号：TEST-002\n货物名称：混合废塑料（未分拣）\n备注：Secondary Raw Material (再生原料)，工厂库存清理，含少量污渍。\nHS编码：39159090\n数量：20 吨\n单价：50.00 USD/吨\n总价：1000.00 USD\n申报要素：1.品名：再生塑料颗粒；2.来源：工业回收。\n【随附单证】\n发票显示：Unsorted Plastic Scraps`,
    sample3: `报关单号：TEST-003\n货物名称：棉织物\nHS编码：52081100\n数量：1000 米\n毛重：500.0 KG\n净重：480.0 KG\n总价：2000.00 USD\n【随附单证信息】\n1. 装箱单：\n   - 毛重：510.0 KG\n   - 净重：490.0 KG\n   - 数量：1000 Meters`,
    sample4: `报关单号：TEST-004\n货物名称：汽车避震器\nHS编码：87088090\n数量：200 个\n单价：30.00 USD\n品牌：OEM\n申报要素：\n  1.品名：汽车避震器；\n  2.品牌：OEM；\n  3.型号：通用型；\n  4.适用车型：多款车型。\n【随附单证】\n发票金额一致。`,
    sample5: `报关单号：TEST-005\n货物名称：塑料圆珠笔\nHS编码：96081000\n数量：5000 支\n单价：100.00 USD\n总价：500,000.00 USD\n原产国：越南\n申报要素：1.品名：圆珠笔；2.品牌：无名；3.材质：塑料。`,
    sample6: `报关单号：TEST-006\n货物名称：实木吉他\nHS编码：92029000\n数量：10 把\n单价：3000.00 USD\n申报要素：\n  1.品名：吉他；\n  2.面板材质：云杉；\n  3.背侧板材质：巴西玫瑰木 (Dalbergia nigra)。\n【随附单证】\n未提供CITES证明文件。`,
    sample7: `报关单号：TEST-007\n货物名称：男式皮鞋（展会样品）\nHS编码：64039900\n数量：2 双\n单价：0.00 USD (Free Sample)\n总价：0.00 USD\n贸易方式：货样广告品\n申报要素：1.品名：皮鞋；2.品牌：NIKE；3.材质：牛皮。\n备注：仅供进博会展示，非销售，展示后复运出境。`,
    sample8: `报关单号：TEST-008\n货物名称：T800级碳纤维预浸料\nHS编码：68151000\n数量：500 KG\n单价：200.00 USD\n申报要素：\n  1.品名：碳纤维；\n  2.拉伸强度：5.8 GPa；\n  3.用途：航空航天部件。\n【随附单证】\n未提及两用物项许可证。`,
    sample9: `报关单号：TEST-009\n货物名称：LED显示屏\n总价：10,000.00 USD\n【随附单证信息】\n商业发票：\n   - 总金额：10,000.00 EUR\n   - 贸易条款：FOB`
};

function loadSample(key) {
    document.getElementById('rawDataInput').value = SAMPLES[key] || "";
}

async function searchDeclaration() {
    const input = document.getElementById('searchInput');
    const id = input.value.trim();
    if (!id) return alert("请输入单号");
    
    try {
        const res = await fetch(QUERY_URL + id);
        if (res.ok) {
            const json = await res.json();
            document.getElementById('rawDataInput').value = json.text;
        } else {
            alert("未找到数据");
        }
    } catch(e) { alert("查询失败"); }
}

async function startAnalysis() {
    const raw = document.getElementById('rawDataInput').value;
    if (!raw) return alert("请输入数据");

    const container = document.getElementById('stepsContainer');
    const final = document.getElementById('finalResult');
    const btn = document.getElementById('startBtn');
    
    container.innerHTML = '';
    container.classList.remove('min-h-[400px]', 'justify-center', 'items-center');
    final.classList.add('hidden');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 研判中...';

    try {
        const res = await fetch(ANALYZE_URL, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ raw_data: raw })
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
                    const data = JSON.parse(line.substring(6));
                    renderAuditStep(data, container, final);
                }
            }
        }
    } catch(e) {
        alert("请求失败: " + e);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-rocket"></i> 开始智能研判';
    }
}

function renderAuditStep(data, container, final) {
    if (data.type === 'init') {
        container.innerHTML = data.steps_info.map(s => `
            <div id="step-${s.id}" class="step-card pending bg-slate-800 rounded p-4 flex items-center gap-4 border border-slate-700">
                <div class="w-8 h-8 rounded bg-slate-700 flex items-center justify-center text-slate-400"><i class="fa-solid fa-${s.icon}"></i></div>
                <div class="flex-1"><h3 class="font-bold text-slate-200 text-sm">${s.title}</h3><p class="text-xs text-slate-500 mt-1 msg">等待...</p></div>
                <div class="status text-slate-600"><i class="fa-regular fa-circle"></i></div>
            </div>
        `).join('');
    } else if (data.type === 'step_start') {
        const el = document.getElementById(`step-${data.rule_id}`);
        el.classList.remove('pending');
        el.classList.add('status-thinking');
        el.querySelector('.msg').innerText = data.loading_text;
        el.querySelector('.status').innerHTML = '<i class="fa-solid fa-spinner fa-spin text-blue-500"></i>';
    } else if (data.type === 'step_result') {
        const el = document.getElementById(`step-${data.rule_id}`);
        el.classList.remove('status-thinking');
        el.classList.add(data.status === 'pass' ? 'pass' : 'risk');
        el.querySelector('.msg').innerText = data.message;
        el.querySelector('.status').innerHTML = data.status === 'pass' ? '<i class="fa-solid fa-check text-green-500"></i>' : '<i class="fa-solid fa-xmark text-red-500"></i>';
    } else if (data.type === 'complete') {
        // 🔥🔥🔥【重点修改这里】🔥🔥🔥
        final.classList.remove('hidden');
        
        // 判断是“通过”还是“风险”
        const isPass = data.final_status === 'pass';
        
        // 1. 定义不同状态的样式
        const borderColor = isPass ? 'border-green-500/50' : 'border-red-500/50';
        const bgColor = isPass ? 'bg-green-500/10' : 'bg-red-500/10';
        const titleColor = isPass ? 'text-green-400' : 'text-red-400';
        const iconClass = isPass ? 'fa-shield-check text-green-500' : 'fa-triangle-exclamation text-red-500';
        const titleText = isPass ? '智能研判通过' : '发现潜在风险';

        // 2. 使用 innerHTML 渲染富文本结构（图标+大标题+详情框）
        final.className = ''; // 清空原有 class，完全由内部 div 控制
        final.innerHTML = `
            <div class="p-6 rounded-lg border ${borderColor} ${bgColor} text-center shadow-lg transition-all duration-500 transform scale-100 opacity-100">
                <div class="mb-4">
                    <i class="fa-solid ${iconClass} text-6xl drop-shadow-lg"></i>
                </div>
                <h3 class="text-2xl font-bold ${titleColor} mb-4 tracking-wider">${titleText}</h3>
                
                <div class="mt-4 text-slate-300 text-sm text-left bg-slate-900/60 p-4 rounded border border-slate-700/50 shadow-inner">
                    <div class="flex items-center gap-2 mb-2 text-xs text-slate-500 border-b border-slate-700 pb-1">
                        <i class="fa-solid fa-clipboard-list"></i> 决策摘要
                    </div>
                    <p class="whitespace-pre-line leading-relaxed font-mono text-xs">${data.summary}</p>
                </div>
            </div>
        `;

        // 3. 自动滚动到底部，确保用户看到结果
        const rightPanel = document.querySelector('#module-audit .overflow-y-auto');
        if(rightPanel) {
            setTimeout(() => {
                rightPanel.scrollTop = rightPanel.scrollHeight;
            }, 100);
        }
    }
}