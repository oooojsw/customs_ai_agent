// ==========================================
// 1. 全局状态缓存 ( 充当本地微型数据库 )
// ==========================================
const llmStateCache = {};

// ==========================================
// 2. 厂商预设
// ==========================================
const PROVIDER_PRESETS = {
    deepseek: { base_url: 'https://api.deepseek.com/v1', models: ['deepseek-chat', 'deepseek-coder', 'deepseek-reasoner'] },
    openai: { base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'] },
    qwen: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen-plus', 'qwen-max', 'qwen-turbo'] },
    zhipu: { base_url: 'https://open.bigmodel.cn/api/paas/v4/', models: ['glm-4', 'glm-4-flash', 'glm-4-plus'] },
    siliconflow: { base_url: 'https://api.siliconflow.cn/v1', models: ['Qwen/Qwen2.5-VL-72B-Instruct', 'deepseek-ai/DeepSeek-V3'] },
    azure: { base_url: '', models: [] },
    custom: { base_url: '', models: [] }
};

// ==========================================
// 3. 实时监听输入 ( 敲击键盘瞬间保存到缓存 )
// ==========================================
let llmFetchModelsTimeout = null;

function setupLLMInputListeners() {
    const inputMapping = {
        'llmApiKey': 'apiKey',
        'llmBaseUrl': 'baseUrl',
        'llmModelName': 'modelName',
        'llmTemperature': 'temperature',
        'llmApiVersion': 'apiVersion'
    };

    Object.keys(inputMapping).forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', (e) => {
                const provider = document.getElementById('llmProvider').value;
                // 如果缓存不存在则初始化
                if (!llmStateCache[provider]) {
                    llmStateCache[provider] = {};
                }
                // 将当前输入值实时存入对应的缓存字段
                const cacheKey = inputMapping[id];
                llmStateCache[provider][cacheKey] = e.target.value;

                // API Key 输入后自动加载模型（防抖处理）
                if (id === 'llmApiKey' && typeof fetchModels === 'function') {
                    clearTimeout(llmFetchModelsTimeout);
                    llmFetchModelsTimeout = setTimeout(() => {
                        fetchModels();
                    }, 800);
                }
            });
        }
    });
}

// ==========================================
// 4. 统一渲染 UI ( 严格根据缓存重绘界面 )
// ==========================================
function renderLLMForm(provider) {
    const state = llmStateCache[provider] || {};
    const preset = PROVIDER_PRESETS[provider] || {};
    
    // 渲染 Key 和 BaseUrl
    document.getElementById('llmApiKey').value = state.apiKey || '';
    document.getElementById('llmBaseUrl').value = state.baseUrl || preset.base_url || '';
    
    // 渲染模型下拉框
    const modelSelect = document.getElementById('llmModelName');
    if (state.modelName) {
        // 如果当前下拉列表没有这个模型，临时加进去防止显示空白
        if (!Array.from(modelSelect.options).some(opt => opt.value === state.modelName)) {
            modelSelect.add(new Option(state.modelName, state.modelName));
        }
        modelSelect.value = state.modelName;
    }
    
    // 渲染 Temperature
    if (state.temperature !== undefined) {
        document.getElementById('llmTemperature').value = state.temperature;
        const tempValue = document.getElementById('tempValue');
        if (tempValue) tempValue.innerText = state.temperature;
    }
    
    // 渲染 Azure 专属字段
    const apiVersionEl = document.getElementById('llmApiVersion');
    if (apiVersionEl && state.apiVersion !== undefined) {
        apiVersionEl.value = state.apiVersion;
    }
}

// ==========================================
// 5. 从后端安全拉取配置 ( 仅在缓存为空时调用 )
// ==========================================
async function fetchProviderConfigFromDB(provider) {
    try {
        const url = `/api/v1/config/llm/provider/${provider}?_t=${Date.now()}`;
        const res = await fetch(url);
        const data = await res.json();

        const preset = PROVIDER_PRESETS[provider] || {};

        if (data.status === 'success' && data.config) {
            // 如果后端返回了掩码形式的 key，则视为空，要求用户重新输入
            let safeKey = data.config.api_key || '';
            if (safeKey.includes('****')) safeKey = '';

            llmStateCache[provider] = {
                apiKey: safeKey,
                baseUrl: data.config.base_url || preset.base_url || '',
                modelName: data.config.model_name || '',
                temperature: data.config.temperature !== undefined ? data.config.temperature : 0.3,
                apiVersion: data.config.api_version || ''
            };
        } else {
            // 后端没有该厂商记录，初始化基础缓存
            llmStateCache[provider] = {
                apiKey: '',
                baseUrl: preset.base_url || '',
                temperature: 0.3
            };
        }
    } catch (e) {
        console.error("从数据库加载配置失败", e);
        llmStateCache[provider] = { apiKey: '', baseUrl: PROVIDER_PRESETS[provider]?.base_url || '' };
    }
}

// ==========================================
// 6. 核心逻辑：切换厂商 ( 解决数据消失的根源 )
// ==========================================
async function updateProviderPresets() {
    const provider = document.getElementById('llmProvider').value;
    
    // 切换 Azure 专属 UI 显示
    if (typeof updateUIForAzure === 'function') {
        updateUIForAzure(provider);
    }

    // 关键防御：如果本地缓存中【没有】这个厂商的数据，才去后端拉取
    // 这样就不会覆盖用户刚输入了一半还没保存的数据
    if (!llmStateCache[provider]) {
        const apiKeyInput = document.getElementById('llmApiKey');
        apiKeyInput.value = '';
        apiKeyInput.placeholder = '正在从服务器同步配置...';
        
        // 等待数据拉取完成
        await fetchProviderConfigFromDB(provider); 
        
        apiKeyInput.placeholder = '请输入 API Key';
    }

    // 根据缓存重绘界面
    renderLLMForm(provider);

    // 数据就绪后，再去拉取可用模型
    if (typeof fetchModels === 'function') {
        fetchModels();
    }
}

// ==========================================
// 7. 初始化逻辑重构
// ==========================================
async function initLLMConfig() {
    // 启动全局键盘监听
    setupLLMInputListeners(); 
    
    try {
        const response = await fetch('/api/v1/config/llm');
        const config = await response.json();
        
        document.getElementById('llmEnabled').checked = config.is_enabled;
        if (typeof toggleLLMFields === 'function') toggleLLMFields();

        const provider = config.provider || 'deepseek';
        document.getElementById('llmProvider').value = provider;
        if (typeof updateUIForAzure === 'function') updateUIForAzure(provider);
        
        // 处理后端的脱敏 Key
        let safeKey = config.api_key || '';
        if (safeKey.includes('****')) safeKey = '';

        // 把激活的配置塞入缓存
        llmStateCache[provider] = {
            apiKey: safeKey,
            baseUrl: config.base_url || '',
            modelName: config.model_name || '',
            temperature: config.temperature !== undefined ? config.temperature : 0.3,
            apiVersion: config.api_version || ''
        };
        
        // 渲染界面
        renderLLMForm(provider);

    } catch (error) {
        console.error('初始化配置失败', error);
    }
}

// ==========================================
// 8. 保存配置
// ==========================================
async function saveLLMConfig() {
    const provider = document.getElementById('llmProvider').value;
    const apiKey = document.getElementById('llmApiKey').value.trim();
    const isEnabled = document.getElementById('llmEnabled').checked;

    if (isEnabled && !apiKey) {
        alert("⚠️ API Key 不能为空！");
        return;
    }

    if (apiKey && apiKey.length < 10) {
        alert("⚠️ API Key 格式不正确");
        return;
    }

    const config = {
        provider: provider,
        api_key: apiKey,
        base_url: document.getElementById('llmBaseUrl').value.trim(),
        model_name: getModelName(),
        temperature: parseFloat(document.getElementById('llmTemperature').value),
        is_enabled: isEnabled,
        api_version: document.getElementById('llmApiVersion')?.value || ''
    };

    try {
        const res = await fetch('/api/v1/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (res.ok) {
            alert("✅ 配置已保存并应用！");
            await fetch('/api/v1/config/llm/reload', { method: 'POST' });
        } else {
            alert("❌ 保存失败");
        }
    } catch (e) {
        alert("❌ 网络请求错误: " + e.message);
    }
}

// ==========================================
// 9. 获取模型列表
// ==========================================
async function fetchModels() {
    const provider = document.getElementById('llmProvider').value;
    const apiKey = document.getElementById('llmApiKey').value;
    const baseUrl = document.getElementById('llmBaseUrl').value;
    const select = document.getElementById('llmModelName');

    if (!apiKey) {
        const presets = PROVIDER_PRESETS[provider]?.models || [];
        if (presets.length > 0) {
            select.innerHTML = presets.map(m => `<option value="${m}">${m}</option>`).join('');
            return;
        }
    }

    try {
        select.innerHTML = '<option value="">加载中...</option>';
        const res = await fetch(`/api/v1/config/llm/models?provider=${provider}&api_key=${encodeURIComponent(apiKey)}&base_url=${encodeURIComponent(baseUrl)}`);
        const data = await res.json();

        if (data.status === 'success' && data.models?.length > 0) {
            select.innerHTML = data.models.map(m => `<option value="${m}">${m}</option>`).join('');
            select.value = data.models[0];
        } else {
            const presets = PROVIDER_PRESETS[provider]?.models || ['deepseek-chat'];
            select.innerHTML = presets.map(m => `<option value="${m}">${m}</option>`).join('');
        }
    } catch (e) {
        select.innerHTML = '<option value="deepseek-chat">deepseek-chat (默认)</option>';
    }
}

// ==========================================
// 10. 辅助函数
// ==========================================
function toggleLLMFields() {
    const enabled = document.getElementById('llmEnabled').checked;
    const form = document.getElementById('llmConfigForm');
    console.log('[toggleLLMFields] enabled:', enabled, 'form element:', !!form);
    form.classList.toggle('hidden', !enabled);
}

function updateUIForAzure(provider) {
    const group = document.getElementById('azureConfigGroup');
    if (group) {
        if (provider === 'azure') {
            group.classList.remove('hidden');
        } else {
            group.classList.add('hidden');
        }
    }
}

function getModelName() {
    const select = document.getElementById('llmModelName');
    return select ? select.value || 'deepseek-chat' : 'deepseek-chat';
}

function testLLMConnection() {
    alert("请直接点击【保存并应用】来验证连通性。");
}

function resetLLMConfig() {
    if(confirm("确定要重置为 .env 默认配置吗？")) {
        fetch('/api/v1/config/llm/reset', { method: 'POST' })
            .then(() => {
                alert("✅ 已重置");
                location.reload();
            })
            .catch(e => console.error('[Reset] 失败:', e));
    }
}

function onApiKeyChanged() {
    const apiKey = document.getElementById('llmApiKey').value;
    const provider = document.getElementById('llmProvider').value;

    if (apiKey && apiKey.length > 10 && provider !== 'zhipu') {
        fetchModels();
    }
}

function togglePasswordVisibility(inputId, iconId) {
    const input = document.getElementById(inputId);
    const icon = document.getElementById(iconId);
    
    // 切换 -webkit-text-security 样式来显示/隐藏密码
    if (input.style.webkitTextSecurity === 'none') {
        input.style.webkitTextSecurity = 'disc';
        icon.className = 'fa-solid fa-eye';
    } else {
        input.style.webkitTextSecurity = 'disc';
        icon.className = 'fa-solid fa-eye';
    }
}

// ==========================================
// 启动
// ==========================================
// 启动
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Init] DOM 加载完成，开始初始化 LLM 配置');
    initLLMConfig().then(() => {
        console.log('[Init] LLM 配置初始化完成');
    }).catch(err => {
        console.error('[Init] LLM 配置初始化失败:', err);
    });
});

// 暴露全局函数
window.toggleLLMFields = toggleLLMFields;
window.onApiKeyChanged = onApiKeyChanged;
window.updateProviderPresets = updateProviderPresets;
window.saveLLMConfig = saveLLMConfig;
window.fetchModels = fetchModels;
window.testLLMConnection = testLLMConnection;
window.resetLLMConfig = resetLLMConfig;
window.togglePasswordVisibility = togglePasswordVisibility;
