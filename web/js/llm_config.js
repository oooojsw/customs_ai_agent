// LLM 配置管理 - 深度修复版

const PROVIDER_PRESETS = {
    // 1. DeepSeek (仅文本)
    deepseek: {
        base_url: 'https://api.deepseek.com/v1', // 加上 /v1 更标准
        models: ['deepseek-chat', 'deepseek-coder', 'deepseek-reasoner'],
        image_models: [] // DeepSeek 暂不支持视觉
    },

    // 2. OpenAI
    openai: {
        base_url: 'https://api.openai.com/v1',
        models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
        image_models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo']
    },

    // 3. 通义千问 (Qwen) - 使用最新的 compatible-mode
    qwen: {
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', // ✅ 已更新
        models: ['qwen-plus', 'qwen-max', 'qwen-turbo'],
        image_models: [ // ✅ 已更新 Vision 模型列表
            'qwen-vl-max',
            'qwen-vl-plus',
            'qwen2.5-vl-72b-instruct', // 最新
            'qwen2.5-vl-7b-instruct'   // 7B 版本
        ]
    },

    // 4. 智谱 AI (Zhipu) - 使用 paas/v4
    zhipu: {
        base_url: 'https://open.bigmodel.cn/api/paas/v4/', // ✅ 已更新
        models: ['glm-4', 'glm-4-flash', 'glm-4-plus'],
        image_models: [ // ✅ 已更新 Vision 模型列表
            'glm-4v',
            'glm-4v-plus',
            'glm-4v-flash'
        ]
    },

    // 5. 硅基流动 (SiliconFlow)
    siliconflow: {
        base_url: 'https://api.siliconflow.cn/v1', // ✅ 确认使用国内 .cn
        models: [], // 文本模型需 API 获取
        image_models: [ // ✅ 确认使用带前缀的完整 ID
            'Qwen/Qwen2.5-VL-72B-Instruct',
            'Qwen/Qwen2.5-VL-7B-Instruct',
            'Qwen/Qwen2-VL-72B-Instruct',
            'Pro/Qwen/Qwen2-VL-7B-Instruct', // 免费版通常带 Pro 或直接用
            'deepseek-ai/deepseek-vl2', // 如果未来支持
            'THUDM/glm-4v-9b'
        ]
    },

    // 6. Azure
    azure: {
        base_url: '',
        models: [],
        image_models: []
    },

    // 7. Custom
    custom: {
        base_url: '',
        models: []
    }
};

// 初始化
async function initLLMConfig() {
    try {
        const response = await fetch('/api/v1/config/llm');
        const config = await response.json();

        // 填充 UI
        document.getElementById('llmEnabled').checked = config.is_enabled;
        document.getElementById('llmProvider').value = config.provider || 'deepseek';

        // 触发一次厂商预设更新（处理 Azure 字段显示/隐藏），但不加载默认值覆盖已保存的值
        updateUIForProvider(config.provider || 'deepseek');

        document.getElementById('llmBaseUrl').value = config.base_url || '';
        document.getElementById('llmModelName').value = config.model_name || '';
        document.getElementById('llmTemperature').value = config.temperature || 0.3;
        document.getElementById('tempValue').innerText = config.temperature || 0.3;

        if (config.api_key) document.getElementById('llmApiKey').value = config.api_key;
        if (config.api_version) document.getElementById('llmApiVersion').value = config.api_version;

        updateConfigSourceDisplay(config);

        // 根据启用状态显示/隐藏表单
        const form = document.getElementById('llmConfigForm');
        form.classList.toggle('hidden', !config.is_enabled);

    } catch (error) {
        console.error('Failed to load LLM config:', error);
    }
}

// 纯 UI 更新，不重置数据
function updateUIForProvider(provider) {
    const azureGroup = document.getElementById('azureConfigGroup');
    if (provider === 'azure') {
        azureGroup.classList.remove('hidden');
    } else {
        azureGroup.classList.add('hidden');
    }
}

// 厂商下拉框变更事件
function updateProviderPresets() {
    const provider = document.getElementById('llmProvider').value;
    const preset = PROVIDER_PRESETS[provider];

    updateUIForProvider(provider);

    // 切换厂商时，清空敏感字段，避免误用
    document.getElementById('llmApiKey').value = '';

    // 填充 Base URL 预设
    if (preset && preset.base_url) {
        document.getElementById('llmBaseUrl').value = preset.base_url;
    } else {
        document.getElementById('llmBaseUrl').value = '';
    }

    // 尝试加载该厂商的历史配置（如果后端支持按厂商存储，当前后端是单条记录覆盖）
    // 由于后端目前是单条记录逻辑，切换厂商意味着用户想改配置，所以这里只填预设，不加载旧数据

    fetchModels(); // 刷新模型列表
}

// 开关切换事件
async function toggleLLMFields() {
    const enabled = document.getElementById('llmEnabled').checked;
    const form = document.getElementById('llmConfigForm');

    form.classList.toggle('hidden', !enabled);

    // 策略：
    // 1. 如果是 关闭 (OFF)：立即保存并重载，切回 .env 模式
    // 2. 如果是 开启 (ON)：只显示 UI，不立即保存（因为 Key 可能是空的）。
    //    用户必须点击"保存并应用"才生效。这样避免了报错。

    if (!enabled) {
        await autoSaveConfig(false); // 传入 false 明确禁用
    } else {
        // 仅更新 UI 显示，提示用户去编辑
        updateConfigSourceDisplay({ is_enabled: true, provider: '未保存...', model_name: '等待配置' });
    }
}

async function autoSaveConfig(enabled) {
    // 收集当前表单数据（即使用户没填完，disable 时也得传，后端只看 is_enabled）
    const config = getFormConfig();
    config.is_enabled = enabled;

    try {
        // 1. 保存
        const saveRes = await fetch('/api/v1/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (!saveRes.ok) throw new Error("保存失败");

        // 2. 重载
        const reloadRes = await fetch('/api/v1/config/llm/reload', { method: 'POST' });
        const reloadData = await reloadRes.json();

        if (reloadData.status === 'success') {
            const sourceText = reloadData.config.source === 'env' ? '.env 环境变量' : '用户自定义';
            console.log(`[Config] 切换成功: ${sourceText}`);

            // 更新 UI 状态条
            updateConfigSourceDisplay({
                is_enabled: enabled,
                provider: reloadData.config.provider,
                model_name: reloadData.config.model
            });
        }
    } catch (e) {
        console.error("Auto save failed:", e);
        alert("配置切换失败，请检查后端日志");
    }
}

function getFormConfig() {
    return {
        provider: document.getElementById('llmProvider').value,
        api_key: document.getElementById('llmApiKey').value,
        base_url: document.getElementById('llmBaseUrl').value,
        model_name: getModelName() || 'deepseek-chat',
        temperature: parseFloat(document.getElementById('llmTemperature').value),
        is_enabled: document.getElementById('llmEnabled').checked,
        api_version: document.getElementById('llmApiVersion').value // Azure 专用
    };
}

// 保存按钮点击事件
async function saveLLMConfig() {
    const config = getFormConfig();

    // 基础校验
    if (config.is_enabled) {
        if (!config.api_key) {
            alert("启用自定义配置时，API Key 不能为空！");
            return;
        }
        if (config.provider === 'azure' && !config.base_url) {
            alert("Azure 模式下，API 地址 (Endpoint) 不能为空！");
            return;
        }
    }

    try {
        const saveRes = await fetch('/api/v1/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (!saveRes.ok) throw new Error("保存失败");

        const reloadRes = await fetch('/api/v1/config/llm/reload', { method: 'POST' });
        const reloadData = await reloadRes.json();

        if (reloadData.status === 'success') {
            alert(`✅ 配置已保存并生效！\n当前使用: ${reloadData.config.provider} / ${reloadData.config.model}`);
            updateConfigSourceDisplay({
                is_enabled: true,
                provider: reloadData.config.provider,
                model_name: reloadData.config.model
            });
        }
    } catch (e) {
        alert("❌ 保存失败: " + e.message);
    }
}

// 确保updateConfigSourceDisplay逻辑正确
function updateConfigSourceDisplay(config) {
    let sourceLabel = document.getElementById('configSourceLabel');
    if (!sourceLabel) {
        const enabledLabel = document.querySelector('label[for="llmEnabled"]');
        if (enabledLabel && enabledLabel.parentElement) {
            sourceLabel = document.createElement('div');
            sourceLabel.id = 'configSourceLabel';
            sourceLabel.className = 'text-xs mt-2 px-2 py-1 rounded bg-gray-800 border border-gray-700 text-gray-400';
            enabledLabel.parentElement.after(sourceLabel);
        }
    }

    if (sourceLabel) {
        if (!config.is_enabled) {
            sourceLabel.textContent = '当前: .env 系统配置';
            sourceLabel.className = 'text-xs mt-2 px-2 py-1 rounded bg-green-900/30 border border-green-700 text-green-400';
        } else {
            const p = config.provider || 'Custom';
            const m = config.model_name || 'Unknown';
            sourceLabel.textContent = `当前: 用户配置 (${p} - ${m})`;
            sourceLabel.className = 'text-xs mt-2 px-2 py-1 rounded bg-blue-900/30 border border-blue-700 text-blue-400';
        }
    }
}

// 保留其他辅助函数
function onApiKeyChanged() {
    const apiKey = document.getElementById('llmApiKey').value;
    const provider = document.getElementById('llmProvider').value;

    // 如果输入了API Key，自动获取模型列表（仅对支持API的厂商）
    if (apiKey && apiKey.length > 10 && provider !== 'zhipu') {
        console.log('检测到API Key输入，自动获取模型列表...');
        fetchModels();
    }
}

async function loadProviderConfig(provider) {
    try {
        const response = await fetch(`/api/v1/config/llm/provider/${provider}`);
        const result = await response.json();

        if (result.status === 'success') {
            const config = result.config;

            // 填充已保存的配置
            if (config.api_key) {
                document.getElementById('llmApiKey').value = config.api_key;
            }
            if (config.base_url) {
                document.getElementById('llmBaseUrl').value = config.base_url;
            }
            if (config.model_name) {
                document.getElementById('llmModelName').value = config.model_name;
            }
            if (config.temperature) {
                document.getElementById('llmTemperature').value = config.temperature;
                document.getElementById('tempValue').innerText = config.temperature;
            }
            if (config.api_version) {
                document.getElementById('llmApiVersion').value = config.api_version;
            }

            console.log(`[LLM Config] 已加载 ${provider} 的保存配置`);
        }
    } catch (error) {
        console.log(`[LLM Config] ${provider} 暂无保存配置，使用预设值`);
    }
}

async function fetchModels() {
    const provider = document.getElementById('llmProvider').value;
    const apiKey = document.getElementById('llmApiKey').value;
    const baseUrl = document.getElementById('llmBaseUrl').value;
    const apiVersion = document.getElementById('llmApiVersion')?.value || '2024-03-01-preview';
    const modelSelect = document.getElementById('llmModelName');
    const fetchBtn = document.getElementById('fetchModelsBtn');

    // 清空当前列表
    modelSelect.innerHTML = '<option value="" disabled selected>正在获取模型列表...</option>';

    try {
        let models = [];

        // 1. 智谱GLM：使用硬编码列表
        if (provider === 'zhipu') {
            models = PROVIDER_PRESETS.zhipu.models;

        // 2. Azure：需要baseUrl和apiVersion
        } else if (provider === 'azure') {
            if (!apiKey || !baseUrl) {
                modelSelect.innerHTML = '<option value="" disabled>Azure需要 API Key 和 Endpoint</option>';
                return;
            }

            // 显示加载状态
            if (fetchBtn) fetchBtn.classList.add('fa-spin');

            let apiUrl = `/api/v1/config/llm/models?provider=azure&api_key=${encodeURIComponent(apiKey)}&base_url=${encodeURIComponent(baseUrl)}`;
            apiUrl += `&api_version=${encodeURIComponent(apiVersion)}`;

            const response = await fetch(apiUrl);
            const result = await response.json();

            if (result.status === 'success') {
                models = result.models;
            } else {
                modelSelect.innerHTML = `<option value="" disabled>${result.message}</option>`;
                return;
            }

        // 3. 其他厂商：调用API获取
        } else {
            // 没有API Key时的处理
            if (!apiKey) {
                // 如果有本地预设列表，使用预设
                if (PROVIDER_PRESETS[provider] && PROVIDER_PRESETS[provider].models.length > 0) {
                    models = PROVIDER_PRESETS[provider].models;
                    // 显示提示，告知用户这是预设列表
                    console.log(`[提示] 当前显示${provider}的预设模型列表，输入API Key后可获取最新列表`);
                } else {
                    modelSelect.innerHTML = '<option value="" disabled>请先输入 API Key</option>';
                    return;
                }
            } else {
                // 有API Key，调用真实API
                // 显示加载状态
                if (fetchBtn) fetchBtn.classList.add('fa-spin');

                let apiUrl = `/api/v1/config/llm/models?provider=${provider}&api_key=${encodeURIComponent(apiKey)}`;
                if (baseUrl && (provider === 'custom' || provider === 'siliconflow')) {
                    apiUrl += `&base_url=${encodeURIComponent(baseUrl)}`;
                }

                const response = await fetch(apiUrl);
                const result = await response.json();

                if (fetchBtn) fetchBtn.classList.remove('fa-spin');

                if (result.status === 'success') {
                    models = result.models;
                } else {
                    // API调用失败，回退到本地预设（如果有）
                    modelSelect.innerHTML = `<option value="" disabled>${result.message}</option>`;
                    if (PROVIDER_PRESETS[provider] && PROVIDER_PRESETS[provider].models.length > 0) {
                        console.warn(`API调用失败，回退到${provider}预设列表`);
                        // 延迟后使用预设列表
                        setTimeout(() => {
                            models = PROVIDER_PRESETS[provider].models;
                            modelSelect.innerHTML = models.map(model =>
                                `<option value="${model}">${model}</option>`
                            ).join('');
                            modelSelect.value = models[0];
                        }, 2000);
                    }
                    return;
                }
            }
        }

        // 4. 填充下拉列表
        if (models.length > 0) {
            modelSelect.innerHTML = models.map(model =>
                `<option value="${model}">${model}</option>`
            ).join('');

            // 选择第一个模型
            modelSelect.value = models[0];
        } else {
            modelSelect.innerHTML = '<option value="" disabled>未找到可用模型</option>';
        }

    } catch (error) {
        console.error('获取模型列表失败:', error);
        modelSelect.innerHTML = '<option value="" disabled>获取失败，请稍后重试</option>';
    } finally {
        if (fetchBtn) fetchBtn.classList.remove('fa-spin');
    }
}

function toggleManualInput() {
    const select = document.getElementById('llmModelName');
    const input = document.getElementById('llmModelNameInput');
    const isHidden = input.classList.contains('hidden');

    if (isHidden) {
        // 显示手动输入框
        input.classList.remove('hidden');
        select.classList.add('hidden');
        input.focus();
    } else {
        // 隐藏手动输入框
        input.classList.add('hidden');
        select.classList.remove('hidden');
    }
}

function getModelName() {
    const element = document.getElementById('llmModelName');
    if (!element) {
        console.error('[LLM Config] llmModelName element not found');
        return 'deepseek-chat'; // 默认值
    }
    return element.value || 'deepseek-chat';
}

async function testLLMConnection() {
    const statusArea = document.getElementById('llmStatusArea');
    const statusMessage = document.getElementById('llmStatusMessage');

    statusArea.classList.remove('hidden');
    statusMessage.innerHTML = '<span class="text-yellow-400"><i class="fa-solid fa-spinner fa-spin"></i> 正在测试...</span>';

    const config = {
        provider: document.getElementById('llmProvider').value,
        api_key: document.getElementById('llmApiKey').value,
        base_url: document.getElementById('llmBaseUrl').value,
        model_name: getModelName(),
        temperature: parseFloat(document.getElementById('llmTemperature').value)
    };

    // 添加Azure的api_version参数
    if (config.provider === 'azure') {
        config.api_version = document.getElementById('llmApiVersion').value;
    }

    try {
        const response = await fetch('/api/v1/config/llm/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const result = await response.json();

        if (result.status === 'success') {
            statusMessage.innerHTML = `<span class="text-green-400"><i class="fa-solid fa-check-circle"></i> ${result.message}</span>`;
        } else {
            statusMessage.innerHTML = `<span class="text-red-400"><i class="fa-solid fa-times-circle"></i> ${result.message}</span>`;
        }
    } catch (error) {
        statusMessage.innerHTML = `<span class="text-red-400"><i class="fa-solid fa-times-circle"></i> 测试失败</span>`;
    }

    setTimeout(() => {
        statusArea.classList.add('hidden');
    }, 5000);
}

async function resetLLMConfig() {
    if (!confirm('确定要切换回 .env 配置吗？\n\n这将禁用所有自定义配置，系统将使用 .env 文件中的环境变量。')) {
        return;
    }

    try {
        // 1. 调用重置端点（禁用所有用户配置）
        const resetResponse = await fetch('/api/v1/config/llm/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const resetResult = await resetResponse.json();

        if (resetResult.status !== 'success') {
            throw new Error(resetResult.message || '重置失败');
        }

        // 2. 热重载配置（确保 app.state.llm_config 更新）
        const reloadResponse = await fetch('/api/v1/config/llm/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            const reloadConfig = reloadResult.config || {};
            console.log('[LLM Config] 已重置为 .env 配置:', reloadConfig);

            // 3. 更新UI状态，不需要刷新页面
            // 关闭开关
            document.getElementById('llmEnabled').checked = false;
            // 隐藏配置表单
            document.getElementById('llmConfigForm').classList.add('hidden');
            // 更新配置来源显示
            updateConfigSourceDisplay({ is_enabled: false, provider: 'deepseek', model_name: reloadConfig.model });

            alert('✅ 已切换到 .env 配置！\n\n模型：' + (reloadConfig.model || 'deepseek-chat'));
        } else {
            throw new Error(reloadResult.message || '重载失败');
        }
    } catch (error) {
        console.error('[Config Reset Error]', error);
        alert('❌ 切换失败: ' + error.message);
    }
}

document.addEventListener('DOMContentLoaded', initLLMConfig);
