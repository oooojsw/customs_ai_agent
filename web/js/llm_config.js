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

        // 填充API Key（如果存在）
        if (config.api_key) {
            document.getElementById('llmApiKey').value = config.api_key;
            console.log('[LLM Config] 已加载保存的API Key');
        }

        // 如果是Azure，填充api_version
        if (config.api_version) {
            document.getElementById('llmApiVersion').value = config.api_version;
        }

        // ✅ 新增：显示当前配置来源
        updateConfigSourceDisplay(config);

        toggleLLMFields();
    } catch (error) {
        console.error('Failed to load LLM config:', error);
    }
}

/**
 * ✅ 新增：更新配置来源显示
 * @param {Object} config - LLM配置对象
 */
function updateConfigSourceDisplay(config) {
    // 获取或创建配置来源标签元素
    let sourceLabel = document.getElementById('configSourceLabel');
    if (!sourceLabel) {
        // 如果不存在，动态创建（添加到开关旁边）
        const enabledLabel = document.querySelector('label[for="llmEnabled"]');
        if (enabledLabel && enabledLabel.parentElement) {
            sourceLabel = document.createElement('div');
            sourceLabel.id = 'configSourceLabel';
            sourceLabel.className = 'text-sm mt-2 px-3 py-2 rounded bg-gray-100 dark:bg-gray-800';
            sourceLabel.style.cssText = 'font-size: 0.875rem; margin-top: 0.5rem; padding: 0.5rem 0.75rem; border-radius: 0.375rem;';
            enabledLabel.parentElement.after(sourceLabel);
        }
    }

    if (sourceLabel) {
        // 根据配置来源显示不同的样式和文本
        if (!config.is_enabled) {
            // 使用.env配置
            sourceLabel.textContent = '✓ 当前配置：.env 环境变量';
            sourceLabel.style.color = '#10b981'; // 绿色
            sourceLabel.style.backgroundColor = '#d1fae5';
            sourceLabel.style.border = '1px solid #10b981';
        } else {
            // 使用用户配置
            const providerName = config.provider || '未知';
            sourceLabel.textContent = `✓ 当前配置：用户自定义 (${providerName}/${config.model_name})`;
            sourceLabel.style.color = '#3b82f6'; // 蓝色
            sourceLabel.style.backgroundColor = '#dbeafe';
            sourceLabel.style.border = '1px solid #3b82f6';
        }
    }

    // 在控制台显示配置来源
    const source = config.is_enabled ? 'user' : 'env';
    console.log(`[LLM Config] 配置来源: ${source}, 模型: ${config.model_name}, 是否启用: ${config.is_enabled}`);
}

function toggleLLMFields() {
    const enabled = document.getElementById('llmEnabled').checked;
    const form = document.getElementById('llmConfigForm');
    form.classList.toggle('hidden', !enabled);

    // ✅ 新增：实时更新配置来源显示（预览模式）
    const config = {
        is_enabled: enabled,
        provider: document.getElementById('llmProvider').value,
        model_name: getModelName()
    };
    updateConfigSourceDisplay(config);

    // ✅ 核心修复：自动保存配置到后端
    autoSaveConfig(enabled);

    // 启用时自动获取模型列表
    if (enabled) {
        fetchModels();
    }
}

/**
 * ✅ 新增：自动保存配置（开关变化时调用）
 * @param {boolean} enabled - 是否启用用户配置
 */
async function autoSaveConfig(enabled) {
    try {
        // 准备配置数据
        const config = {
            provider: document.getElementById('llmProvider').value,
            api_key: document.getElementById('llmApiKey').value,
            base_url: document.getElementById('llmBaseUrl').value,
            model_name: getModelName() || 'deepseek-chat', // 默认值
            temperature: parseFloat(document.getElementById('llmTemperature').value),
            is_enabled: enabled
        };

        // Azure 特殊处理
        if (config.provider === 'azure') {
            config.api_version = document.getElementById('llmApiVersion').value;
        }

        // 如果启用但没有 API Key，提示用户但不阻止
        if (enabled && !config.api_key) {
            console.warn('[LLM Config] 启用了自定义配置但未填写 API Key');
        }

        // 1. 保存配置
        const saveResponse = await fetch('/api/v1/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const saveResult = await saveResponse.json();

        if (saveResult.status !== 'success') {
            console.error('[LLM Config] 保存失败:', saveResult.message);
            return;
        }

        console.log(`[LLM Config] 配置已${enabled ? '启用' : '禁用'}，正在热重载...`);

        // 2. 热重载配置
        const reloadResponse = await fetch('/api/v1/config/llm/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            const reloadConfig = reloadResult.config || {};
            const sourceText = reloadConfig.source === 'env' ? '.env 环境变量' : '用户自定义';
            console.log(`[LLM Config] ✓ 热重载成功！当前配置来源：${sourceText}`);
        } else {
            console.error('[LLM Config] 热重载失败:', reloadResult.message);
        }

    } catch (error) {
        console.error('[LLM Config] 自动保存失败:', error);
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
        temperature: parseFloat(document.getElementById('llmTemperature').value),
        is_enabled: document.getElementById('llmEnabled').checked  // 包含开关状态
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

        console.log('[LLM Config] 配置已保存');

        // 2. 热重载配置
        const reloadResponse = await fetch('/api/v1/config/llm/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            const reloadConfig = reloadResult.config || {};
            const sourceText = reloadConfig.source === 'env' ? '.env 环境变量' : '用户自定义';
            console.log('[LLM Config] 配置已重载:', reloadConfig);

            // ✅ 优化：显示简洁的提示，不再刷新页面
            alert(`✅ 配置已保存并应用！\n\n当前配置来源：${sourceText}\n模型：${reloadConfig.model || config.model_name}`);

            // ✅ 优化：更新配置来源显示（不需要刷新页面）
            updateConfigSourceDisplay(config);
        } else {
            throw new Error(reloadResult.message);
        }
    } catch (error) {
        alert('❌ 操作失败: ' + error.message);
    }
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

            // 3. ✅ 优化：更新UI状态，不需要刷新页面
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
