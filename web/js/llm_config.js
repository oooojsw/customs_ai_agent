// LLM 配置管理

const PROVIDER_PRESETS = {
    deepseek: {
        base_url: 'https://api.deepseek.com',
        models: ['deepseek-chat', 'deepseek-coder', 'deepseek-reasoner']
    },
    openai: {
        base_url: 'https://api.openai.com/v1',
        models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo']
    },
    qwen: {
        base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        models: ['qwen-turbo', 'qwen-plus', 'qwen-max', 'qwen-max-longcontext']
    },
    zhipu: {
        base_url: 'https://open.bigmodel.cn/api/paas/v4/',
        models: ['glm-4.7', 'glm-4-turbo', 'glm-4-plus', 'glm-4-air', 'glm-4-flash']
    },
    siliconflow: {
        base_url: 'https://api.siliconflow.cn/v1',
        models: []  // 需要通过API获取
    },
    azure: {
        base_url: '',  // 用户需要自己输入
        models: []     // 需要通过API获取
    },
    custom: {
        base_url: '',
        models: []     // 需要通过API获取
    }
};

// 初始化
async function initLLMConfig() {
    try {
        const response = await fetch('/api/v1/config/llm');
        const config = await response.json();

        document.getElementById('llmEnabled').checked = config.is_enabled;
        document.getElementById('llmProvider').value = config.provider;
        document.getElementById('llmBaseUrl').value = config.base_url;
        document.getElementById('llmModelName').value = config.model_name;
        document.getElementById('llmTemperature').value = config.temperature;
        document.getElementById('tempValue').innerText = config.temperature;

        toggleLLMFields();
    } catch (error) {
        console.error('Failed to load LLM config:', error);
    }
}

function toggleLLMFields() {
    const enabled = document.getElementById('llmEnabled').checked;
    const form = document.getElementById('llmConfigForm');
    form.classList.toggle('hidden', !enabled);

    // 启用时自动获取模型列表
    if (enabled) {
        fetchModels();
    }
}

function onApiKeyChanged() {
    const apiKey = document.getElementById('llmApiKey').value;
    const provider = document.getElementById('llmProvider').value;

    // 如果输入了API Key，自动获取模型列表（仅对支持API的厂商）
    if (apiKey && apiKey.length > 10 && provider !== 'zhipu') {
        console.log('检测到API Key输入，自动获取模型列表...');
        fetchModels();
    }
}

function updateProviderPresets() {
    const provider = document.getElementById('llmProvider').value;
    const preset = PROVIDER_PRESETS[provider];
    const azureGroup = document.getElementById('azureApiVersionGroup');

    // 1. 显示/隐藏Azure API Version字段
    if (provider === 'azure') {
        azureGroup.classList.remove('hidden');
    } else {
        azureGroup.classList.add('hidden');
    }

    // 2. 先加载已保存的配置（如果有）
    loadProviderConfig(provider);

    // 3. 如果没有保存的配置，使用预设base_url
    const currentBaseUrl = document.getElementById('llmBaseUrl').value;
    if (!currentBaseUrl && preset && preset.base_url) {
        document.getElementById('llmBaseUrl').value = preset.base_url;
    }

    // 4. 获取模型列表
    fetchModels();
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
    const useManual = !document.getElementById('llmModelNameInput').classList.contains('hidden');
    return useManual
        ? document.getElementById('llmModelNameInput').value
        : document.getElementById('llmModelName').value;
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

async function saveLLMConfig() {
    const modelName = getModelName();
    if (!modelName) {
        alert('❌ 请选择或输入模型名称');
        return;
    }

    const config = {
        provider: document.getElementById('llmProvider').value,
        api_key: document.getElementById('llmApiKey').value,
        base_url: document.getElementById('llmBaseUrl').value,
        model_name: modelName,
        temperature: parseFloat(document.getElementById('llmTemperature').value)
    };

    // 添加Azure的api_version参数
    if (config.provider === 'azure') {
        config.api_version = document.getElementById('llmApiVersion').value;
    }

    try {
        // 1. 保存配置
        const saveResponse = await fetch('/api/v1/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const saveResult = await saveResponse.json();

        if (saveResult.status !== 'success') {
            throw new Error(saveResult.message);
        }

        // 2. 热重载配置
        const reloadResponse = await fetch('/api/v1/config/llm/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            alert('✅ 配置已保存并应用！');
            toggleSettings();
        } else {
            throw new Error(reloadResult.message);
        }
    } catch (error) {
        alert('❌ 操作失败: ' + error.message);
    }
}

async function resetLLMConfig() {
    if (!confirm('确定要重置为 .env 默认配置吗？')) return;

    try {
        const response = await fetch('/api/v1/config/llm/reset', {
            method: 'POST'
        });

        const result = await response.json();

        if (result.status === 'success') {
            alert('✅ 已重置，正在重新加载...');
            location.reload();
        } else {
            alert('❌ 重置失败: ' + result.message);
        }
    } catch (error) {
        alert('❌ 重置失败: ' + error.message);
    }
}

document.addEventListener('DOMContentLoaded', initLLMConfig);
