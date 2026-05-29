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
    setRawDataValue(SAMPLES[key] || "");
}

function setRawDataValue(value) {
    const textarea = document.getElementById('rawDataInput');
    if (!textarea) return;
    textarea.value = value;
    renderRawDataPreview();
}

function sanitizeMarkdownHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    template.content.querySelectorAll('script, iframe, object, embed, link, meta').forEach(el => el.remove());
    template.content.querySelectorAll('*').forEach(el => {
        [...el.attributes].forEach(attr => {
            const name = attr.name.toLowerCase();
            const value = attr.value.trim().toLowerCase();
            if (name.startsWith('on') || value.startsWith('javascript:')) {
                el.removeAttribute(attr.name);
            }
        });
    });
    return template.innerHTML;
}

function renderRawDataPreview() {
    const textarea = document.getElementById('rawDataInput');
    const preview = document.getElementById('rawDataPreview');
    if (!textarea || !preview) return;

    const raw = textarea.value || '';
    if (window.marked) {
        preview.innerHTML = sanitizeMarkdownHtml(marked.parse(raw, { breaks: true }));
    } else {
        preview.textContent = raw;
    }
}

function switchRawDataMode(mode) {
    const textarea = document.getElementById('rawDataInput');
    const preview = document.getElementById('rawDataPreview');
    const editTab = document.getElementById('rawDataEditTab');
    const previewTab = document.getElementById('rawDataPreviewTab');
    if (!textarea || !preview || !editTab || !previewTab) return;

    const isPreview = mode === 'preview';
    if (isPreview) {
        renderRawDataPreview();
    }
    textarea.classList.toggle('hidden', isPreview);
    preview.classList.toggle('hidden', !isPreview);

    editTab.classList.toggle('active', !isPreview);
    editTab.classList.toggle('text-cyan-300', !isPreview);
    editTab.classList.toggle('bg-cyan-500/10', !isPreview);
    editTab.classList.toggle('border-cyan-500/40', !isPreview);
    editTab.classList.toggle('text-slate-400', isPreview);
    editTab.classList.toggle('border-transparent', isPreview);

    previewTab.classList.toggle('active', isPreview);
    previewTab.classList.toggle('text-cyan-300', isPreview);
    previewTab.classList.toggle('bg-cyan-500/10', isPreview);
    previewTab.classList.toggle('border-cyan-500/40', isPreview);
    previewTab.classList.toggle('text-slate-400', !isPreview);
    previewTab.classList.toggle('border-transparent', !isPreview);
}

document.addEventListener('DOMContentLoaded', () => {
    const textarea = document.getElementById('rawDataInput');
    if (textarea) {
        textarea.addEventListener('input', renderRawDataPreview);
    }
});

let imagePreviewObjectUrl = null;

function handleImageSelection(input) {
    const file = input.files && input.files[0];
    const fileNameDisplay = document.getElementById('fileNameDisplay');
    const previewWrap = document.getElementById('imagePreviewWrap');
    const preview = document.getElementById('imagePreview');

    if (imagePreviewObjectUrl) {
        URL.revokeObjectURL(imagePreviewObjectUrl);
        imagePreviewObjectUrl = null;
    }

    if (fileNameDisplay) {
        fileNameDisplay.innerText = file ? file.name : t('select_image');
    }

    if (!previewWrap || !preview) return;

    if (!file) {
        preview.removeAttribute('src');
        previewWrap.classList.add('hidden');
        return;
    }

    imagePreviewObjectUrl = URL.createObjectURL(file);
    preview.src = imagePreviewObjectUrl;
    previewWrap.classList.remove('hidden');
}

async function searchDeclaration() {
    const input = document.getElementById('searchInput');
    const id = input.value.trim();
    if (!id) return alert(t('please_input_id'));

    try {
        const res = await fetch(QUERY_URL + id);
        if (res.ok) {
            const json = await res.json();
            setRawDataValue(json.text);
        } else {
            alert(t('no_data_found'));
        }
    } catch(e) { alert(t('query_failed')); }
}

async function startAnalysis() {
    const raw = document.getElementById('rawDataInput').value;
    if (!raw) return alert(t('please_input_data'));

    const container = document.getElementById('stepsContainer');
    const final = document.getElementById('finalResult');
    const btn = document.getElementById('startBtn');

    container.innerHTML = '';
    container.classList.remove('min-h-[400px]', 'justify-center', 'items-center');
    final.classList.add('hidden');
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${t('analyzing')}...`;

    try {
        const res = await fetch(ANALYZE_URL, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ raw_data: raw, language: window.currentLanguage })
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
        alert(`${t('request_failed')}: ` + e);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-rocket"></i> ${t('start_analysis')}`;
    }
}

function renderAuditStep(data, container, final) {
    if (data.type === 'init') {
        container.innerHTML = data.steps_info.map(s => `
            <div id="step-${s.id}" class="step-card pending bg-slate-800 rounded p-4 flex items-start gap-4 border border-slate-700">
                <div class="w-8 h-8 rounded bg-slate-700 flex items-center justify-center text-slate-400 mt-1"><i class="fa-solid fa-${s.icon}"></i></div>
                <div class="flex-1">
                    <h3 class="font-bold text-slate-200 text-sm mb-1">${s.title}</h3>
                    <p class="text-xs text-slate-500 msg">${t('waiting')}</p>
                </div>
                <div class="status text-slate-600 mt-1"><i class="fa-regular fa-circle"></i></div>
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
        const titleText = isPass ? t('audit_pass') : t('audit_risk');

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
                        <i class="fa-solid fa-clipboard-list"></i> ${t('decision_summary')}
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

// --- 新增图片识别逻辑 ---
// --- RAG 文件展开/收起功能 ---
function bindRagClickEvents() {
    const ragLabels = document.querySelectorAll('.rag-file-label');

    ragLabels.forEach(label => {
        label.addEventListener('click', async function(e) {
            e.preventDefault();
            e.stopPropagation();

            const ragContent = this.nextElementSibling;
            const chevron = this.querySelector('.chevron-icon');
            const stepCard = this.closest('.step-card');
            const ruleId = stepCard.id.replace('step-', '');

            // 切换显示/隐藏
            if (ragContent.classList.contains('hidden')) {
                // 展开前检查是否已经加载过
                if (ragContent.querySelector('.loading-rag')) {
                    await loadRagContent(ruleId, ragContent);
                }
                ragContent.classList.remove('hidden');
                chevron.style.transform = 'rotate(90deg)';
            } else {
                // 收起
                ragContent.classList.add('hidden');
                chevron.style.transform = 'rotate(0deg)';
            }
        });
    });
}

async function loadRagContent(ruleId, ragContentDiv) {
    try {
        // 从配置中获取规则信息
        const config = await getRuleConfig();
        const rule = config.rules.find(r => r.id === ruleId);

        if (!rule || !rule.rag_file) {
            ragContentDiv.innerHTML = `<p class="text-red-400">${t('no_rag_file')}</p>`;
            return;
        }

        // 模拟加载 RAG 文件内容
        // 实际项目中，这里应该调用 API 获取文件内容
        const ragContent = await simulateRagLoad(rule.rag_file);

        ragContentDiv.innerHTML = `
            <div class="rag-file-header flex items-center gap-2 mb-2 pb-2 border-b border-slate-700">
                <i class="fa-solid fa-file-lines text-blue-400"></i>
                <span class="text-blue-400 font-semibold">${rule.rag_file}</span>
            </div>
            <div class="rag-file-content whitespace-pre-wrap font-mono text-xs leading-relaxed">
${ragContent}
            </div>
        `;

    } catch (error) {
        console.error('加载 RAG 文件失败:', error);
        ragContentDiv.innerHTML = `<p class="text-red-400">${t('load_file_failed')}</p>`;
    }
}

async function getRuleConfig() {
    // 这里应该从 API 获取配置，现在先用本地配置模拟
    const response = await fetch('/config/risk_rules.json?' + Date.now());
    if (response.ok) {
        return await response.json();
    }
    // 返回默认配置
    return {
        "rules": [
            {
                "id": "R01_BASIC_INFO",
                "rag_file": "rag_r01_basic_info.txt"
            },
            {
                "id": "R02_SENSITIVE_GOODS",
                "rag_file": "rag_r02_sensitive_goods.txt"
            },
            {
                "id": "R03_PRICE_LOGIC",
                "rag_file": "rag_r03_price_logic.txt"
            },
            {
                "id": "R04_HS_CLASSIFICATION",
                "rag_file": "rag_r04_hs_classification.txt"
            },
            {
                "id": "R05_DOC_MATCH",
                "rag_file": "rag_r05_doc_match.txt"
            }
        ]
    };
}

async function simulateRagLoad(filename) {
    // 模拟读取 RAG 文件内容
    // 实际项目中，这里应该读取服务器上的文件内容
    const ragContents = {
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
   - 样品品：通常价格为零或很低
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

        'rag_r04_hs_classification.txt': `【归类一致性分析 - 审查指导文件】

审查要点：
1. 归类一致性检查：
   - 货物名称与 HS 编码匹配
   - 功能用途与申报归类一致
   - 成分构成支持申报归类
   - 实际用途与申报相符

2. 低归高走风险识别：
   - 成品 vs 零件：申报零件，实际是成品
   - 组装件 vs 整机：申报散件，实际是整机
   - 功能部件 vs 基础件：申报低档件，实际是高档件
   - 品牌商品 vs 无牌商品：申报无品牌，实际有品牌

3. HS 编码审查重点：
   - 第 16 类机电产品：重点审查功能用途
   - 第 6 类化工产品：重点审查成分比例
   - 第 11 类纺织品类：重点确认纤维成分
   - 第 87 类车辆：重点确认功能和配置

4. 辅助判断方法：
   - 查阅归类决定和预归类
   - 参考同类商品历史归类
   - 核对商品描述与 HS 注释
   - 咨询专业归类意见

5. 常见归类问题：
   - 商品功能描述不清
   - 技术参数不完整
   - 成分比例不准确
   - 品牌信息不完整

6. 风险等级判定：
   - 低风险：归类合理，依据充分
   - 中风险：归类可能偏差，需核实
   - 高风险：归类明显错误，涉嫌归类不实`,

        'rag_r05_doc_match.txt': `【单证一致性交叉比对 - 审查指导文件】

审查要点：
1. 金额一致性检查：
   - 发票金额 vs 报关单申报金额
   - 总金额、单价、数量逻辑关系
   - 币制与汇率正确性
   - 价格条款与贸易方式匹配

2. 重量数据比对：
   - 毛重 vs 净重 vs 皮重逻辑
   - 报关单重量 vs 装箱单重量
   - 数量与重量比例合理性
   - 计量单位准确性

3. 单证信息核验：
   - 发票号连续性
   - 装箱单与提运单号对应
   - 原产地证书信息一致
   - 检验检疫证书记录匹配

4. 时间逻辑审查：
   - 发票日期与报关日期合理
   - 运输日期与报关时间匹配
   - 有效期检查（检验证、产地证）
   - 合同执行时间合理性

5. 包装信息核验：
   - 包装种类与实际相符
   - 包装数量与申报一致
   - 包装材料符合要求
   - 危险品包装标识正确

6. 常见不一致情况：
   - 金额差异无说明
   - 重量单位混淆
   - 单证编号不对应
   - 原产地信息冲突

7. 风险判定标准：
   - 轻微差异：合理解释说明
   - 明显矛盾：需提供证明材料
   - 严重不符：可能存在申报不实`
    };

    // 模拟网络延迟
    await new Promise(resolve => setTimeout(resolve, 500));
    return ragContents[filename] || t('no_file_content');
}

// --- 新增图片识别逻辑 ---
async function analyzeImage() {
    const input = document.getElementById('imageInput');
    const btn = document.getElementById('imageAnalyzeBtn');
    const file = input.files && input.files[0];

    if (!file) { alert(t('select_image_first')); return; }

    // UI Loading
    const originalContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('language', window.currentLanguage);

        const response = await fetch(IMAGE_API_URL, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || t('recognition_error'));
        }

        const resJson = await response.json();

        // 填入文本框
        const textarea = document.getElementById('rawDataInput');
        setRawDataValue(resJson.text || '');
        switchRawDataMode('preview');

        // 视觉反馈 (高亮闪烁)
        textarea.parentElement.classList.add('neon-border');
        setTimeout(() => textarea.parentElement.classList.remove('neon-border'), 1000);

        // 自动触发审单 (可选，如果不想自动开始就把下面这行注释掉)
        // await startAnalysis();

    } catch (e) {
        console.error(e);
        alert(`${t('image_recognition_failed')} ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalContent;
    }
}
