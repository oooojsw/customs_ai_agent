// 图像识别配置管理

// PROVIDER_PRESETS 已在 llm_config.js 中定义，此处直接复用
// 初始化
async function initImageConfig() {
    try {
        console.log('[Image Config] 开始加载图像识别配置...');
        const response = await fetch('/api/v1/config/image');
        const config = await response.json();

        console.log('[Image Config] 服务器返回配置:', config);

        // 填充基础字段
        document.getElementById('imageEnabled').checked = config.is_enabled;
        document.getElementById('imageProvider').value = config.provider;
        document.getElementById('imageApiKey').value = config.api_key || '';
        document.getElementById('imageBaseUrl').value = config.base_url || '';

        // 模型名称：现在使用下拉选择框
        const modelSelect = document.getElementById('imageModelName');
        if (config.model_name) {
            // 如果有保存的模型，添加到选项中并选中
            const option = document.createElement('option');
            option.value = config.model_name;
            option.textContent = config.model_name;
            modelSelect.innerHTML = '';
            modelSelect.appendChild(option);
            modelSelect.value = config.model_name;
            console.log(`[Image Config] 已加载模型: ${config.model_name}`);
        } else {
            modelSelect.innerHTML = '<option value="">请选择服务商后点击刷新按钮</option>';
        }

        document.getElementById('imageTemperature').value = config.temperature;
        document.getElementById('imageTempValue').innerText = config.temperature;

        // ✅ 根据 provider 显示/隐藏 Azure 专用配置字段
        const azureGroup = document.getElementById('imageAzureGroup');
        if (config.provider === 'azure') {
            // 只对 Azure 填充专用字段
            if (config.endpoint) {
                document.getElementById('imageEndpoint').value = config.endpoint;
            }
            if (config.api_version) {
                document.getElementById('imageApiVersion').value = config.api_version;
            }
            azureGroup.classList.remove('hidden');
            console.log('[Image Config] 显示 Azure 专用配置字段');
        } else {
            // 非 Azure：清空专用字段并隐藏
            document.getElementById('imageEndpoint').value = '';
            document.getElementById('imageApiVersion').value = '';
            azureGroup.classList.add('hidden');
            console.log('[Image Config] 隐藏 Azure 专用配置字段');
        }

        // 显示配置状态
        if (!config.is_enabled && config.provider) {
            console.warn('[Image Config] ⚠️  当前配置未启用');
            console.warn('[Image Config] 配置已保存但"启用自定义配置"开关未勾选');
            console.warn('[Image Config] 如需使用此配置，请勾选开关并点击"保存并应用"');
        }

        toggleImageFields();
        console.log('[Image Config] ✓ 配置加载完成');
    } catch (error) {
        console.error('[Image Config] 加载配置失败:', error);
    }
}

function toggleImageFields() {
    const enabled = document.getElementById('imageEnabled').checked;
    const form = document.getElementById('imageConfigForm');
    form.classList.toggle('hidden', !enabled);

    // 不再自动保存，让用户手动点击"保存并应用"按钮
    console.log(`[Image Config] 配置表单${enabled ? '显示' : '隐藏'}`);
}

async function autoSaveImageConfig(enabled) {
    try {
        const config = {
            provider: document.getElementById('imageProvider').value,
            api_key: document.getElementById('imageApiKey').value,
            base_url: document.getElementById('imageBaseUrl').value,
            model_name: document.getElementById('imageModelName').value || 'gpt-4-vision',
            temperature: parseFloat(document.getElementById('imageTemperature').value),
            is_enabled: enabled
        };

        // Azure 特殊处理
        if (config.provider === 'azure') {
            config.endpoint = document.getElementById('imageEndpoint').value;
            config.api_version = document.getElementById('imageApiVersion').value;
        }

        if (enabled && !config.api_key) {
            console.warn('[Image Config] 启用了自定义配置但未填写 API Key');
        }

        // 保存配置
        const saveResponse = await fetch('/api/v1/config/image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const saveResult = await saveResponse.json();

        if (saveResult.status !== 'success') {
            console.error('[Image Config] 保存失败:', saveResult.message);
            return;
        }

        console.log('[Image Config] 配置已保存');

        // 热重载配置
        const reloadResponse = await fetch('/api/v1/config/image/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            console.log('[Image Config] ✓ 热重载成功！');
        } else {
            console.error('[Image Config] 热重载失败:', reloadResult.message);
        }

    } catch (error) {
        console.error('[Image Config] 自动保存失败:', error);
    }
}

function updateImageProviderPresets() {
    const provider = document.getElementById('imageProvider').value;
    const preset = PROVIDER_PRESETS[provider];
    const azureGroup = document.getElementById('imageAzureGroup');

    console.log(`[Image Config] 切换服务商到: ${provider}`);
    console.log(`[Image Config] 预设 Base URL: ${preset?.base_url || '(无)'}`);

    // 1. 显示/隐藏Azure API Version字段
    if (provider === 'azure') {
        azureGroup.classList.remove('hidden');
    } else {
        azureGroup.classList.add('hidden');
    }

    // 2. 先清空所有字段（避免残留旧服务商的配置）
    document.getElementById('imageBaseUrl').value = '';
    document.getElementById('imageApiKey').value = '';
    document.getElementById('imageModelName').innerHTML = '<option value="">请先选择服务商并点击刷新</option>';
    console.log(`[Image Config] 已清空所有字段`);

    // 3. 立即填充预设base_url（确保切换服务商时URL正确）
    if (preset && preset.base_url) {
        document.getElementById('imageBaseUrl').value = preset.base_url;
        console.log(`[Image Config] 已填充预设 Base URL: ${preset.base_url}`);
    }

    // 4. 异步加载已保存的配置（会覆盖预设值）
    loadProviderConfig(provider);

    // 5. 最终确认Base URL（打印调试信息）
    setTimeout(() => {
        const finalBaseUrl = document.getElementById('imageBaseUrl').value;
        console.log(`[Image Config] 最终 Base URL: ${finalBaseUrl || '(空)'}`);
    }, 100);

    // 6. 获取模型列表
    fetchImageModels();
}

async function loadProviderConfig(provider) {
    try {
        const response = await fetch(`/api/v1/config/image/provider/${provider}`);
        const result = await response.json();

        if (result.status === 'success') {
            const config = result.config;

            console.log(`[Image Config] 找到 ${provider} 的保存配置`);
            console.log(`[Image Config] 保存的 base_url: ${config.base_url || '(空)'}`);

            // 验证：检查base_url是否与当前provider匹配（简单的域名验证）
            const providerDomains = {
                'siliconflow': 'siliconflow.cn',
                'deepseek': 'deepseek.com',
                'openai': 'openai.com',
                'qwen': 'aliyuncs.com',
                'zhipu': 'bigmodel.cn',
                'azure': 'openai.azure.com'
            };

            // 如果保存的base_url明显不匹配当前provider，发出警告但仍然加载
            if (config.base_url && providerDomains[provider]) {
                const expectedDomain = providerDomains[provider];
                if (!config.base_url.includes(expectedDomain)) {
                    console.warn(`[Image Config] ⚠️  保存的 Base URL 与预期不符`);
                    console.warn(`[Image Config] 预期域名: ${expectedDomain}`);
                    console.warn(`[Image Config] 实际域名: ${config.base_url}`);
                    console.warn(`[Image Config] 仍然加载此配置，请确认是否正确`);
                    // 不再 return，继续加载配置
                }
            }

            // 填充已保存的配置
            if (config.api_key && config.api_key !== 'sk-......') {  // 避免加载脱敏的API Key
                document.getElementById('imageApiKey').value = config.api_key;
                console.log(`[Image Config] 已加载 API Key`);
            }
            if (config.base_url) {
                document.getElementById('imageBaseUrl').value = config.base_url;
                console.log(`[Image Config] 已加载 base_url: ${config.base_url}`);
            }
            if (config.model_name) {
                const modelSelect = document.getElementById('imageModelName');
                // 添加到选项并选中
                const option = document.createElement('option');
                option.value = config.model_name;
                option.textContent = config.model_name;
                modelSelect.innerHTML = '';  // 清空默认选项
                modelSelect.appendChild(option);
                modelSelect.value = config.model_name;
                console.log(`[Image Config] 已加载模型: ${config.model_name}`);
            }
            if (config.endpoint) {
                document.getElementById('imageEndpoint').value = config.endpoint;
            }
            if (config.api_version) {
                document.getElementById('imageApiVersion').value = config.api_version;
            }

            console.log(`[Image Config] ✓ 已加载 ${provider} 的保存配置`);
        } else {
            console.log(`[Image Config] ${provider} 暂无保存配置，使用预设值`);
        }
    } catch (error) {
        console.log(`[Image Config] ${provider} 加载配置失败: ${error.message}`);
    }
}

async function fetchImageModels() {
    const provider = document.getElementById('imageProvider').value;
    const apiKey = document.getElementById('imageApiKey').value;
    const baseUrl = document.getElementById('imageBaseUrl').value;
    const apiVersion = document.getElementById('imageApiVersion')?.value || '2024-03-01-preview';
    const modelSelect = document.getElementById('imageModelName');
    const fetchBtn = document.querySelector('button[onclick="fetchImageModels()"] i');

    // 清空当前列表
    modelSelect.innerHTML = '<option value="">正在获取模型列表...</option>';

    try {
        let models = [];

        // 1. 智谱GLM：使用硬编码列表
        if (provider === 'zhipu') {
            models = PROVIDER_PRESETS.zhipu.models;

        // 2. Azure：需要baseUrl和apiVersion
        } else if (provider === 'azure') {
            if (!apiKey || !baseUrl) {
                modelSelect.innerHTML = '<option value="">Azure需要 API Key 和 Endpoint</option>';
                return;
            }

            // 显示加载状态
            if (fetchBtn) fetchBtn.classList.add('fa-spin');

            let apiUrl = `/api/v1/config/image/models?provider=azure&api_key=${encodeURIComponent(apiKey)}&base_url=${encodeURIComponent(baseUrl)}`;
            apiUrl += `&api_version=${encodeURIComponent(apiVersion)}`;

            const response = await fetch(apiUrl);
            const result = await response.json();

            if (fetchBtn) fetchBtn.classList.remove('fa-spin');

            if (result.status === 'success') {
                models = result.models;
            } else {
                modelSelect.innerHTML = `<option value="">${result.message}</option>`;
                return;
            }

        // 3. 其他厂商：调用API获取
        } else {
            // 没有API Key时的处理
            if (!apiKey) {
                // 如果有本地预设列表，使用预设
                // 优先查找 image_models 字段（图像专用模型），回退到 models 字段
                const presetModels = PROVIDER_PRESETS[provider]?.image_models || PROVIDER_PRESETS[provider]?.models;

                if (presetModels && presetModels.length > 0) {
                    models = presetModels;
                    console.log(`[Image Config] 使用预设模型列表 (${provider}): ${models.length} 个模型`);
                } else {
                    modelSelect.innerHTML = '<option value="">请先输入 API Key</option>';
                    return;
                }
            } else {
                // 有API Key，调用真实API
                // 显示加载状态
                if (fetchBtn) fetchBtn.classList.add('fa-spin');

                let apiUrl = `/api/v1/config/image/models?provider=${provider}&api_key=${encodeURIComponent(apiKey)}`;
                if (baseUrl && (provider === 'custom' || provider === 'siliconflow')) {
                    apiUrl += `&base_url=${encodeURIComponent(baseUrl)}`;
                }

                const response = await fetch(apiUrl);
                const result = await response.json();

                if (fetchBtn) fetchBtn.classList.remove('fa-spin');

                if (result.status === 'success') {
                    models = result.models;
                } else {
                    modelSelect.innerHTML = `<option value="">${result.message}</option>`;
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
            modelSelect.innerHTML = '<option value="">未找到可用模型</option>';
        }

    } catch (error) {
        console.error('获取模型列表失败:', error);
        modelSelect.innerHTML = '<option value="">获取失败，请稍后重试</option>';
    } finally {
        if (fetchBtn) fetchBtn.classList.remove('fa-spin');
    }
}

async function testImageConnection() {
    const statusArea = document.getElementById('imageStatusArea');
    const statusMessage = document.getElementById('imageStatusMessage');

    statusArea.classList.remove('hidden');
    statusMessage.innerHTML = '<span class="text-yellow-400"><i class="fa-solid fa-spinner fa-spin"></i> 正在测试...</span>';

    const config = {
        provider: document.getElementById('imageProvider').value,
        api_key: document.getElementById('imageApiKey').value,
        base_url: document.getElementById('imageBaseUrl').value,
        model_name: document.getElementById('imageModelName').value,
        temperature: parseFloat(document.getElementById('imageTemperature').value)
    };

    // Azure 特有配置
    if (config.provider === 'azure') {
        config.endpoint = document.getElementById('imageEndpoint').value;
        config.api_version = document.getElementById('imageApiVersion').value;
    }

    try {
        const response = await fetch('/api/v1/config/image/test', {
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

async function saveImageConfig() {
    const modelName = document.getElementById('imageModelName').value;
    if (!modelName) {
        alert('❌ 请先点击刷新按钮获取模型列表，或选择服务商');
        return;
    }

    const config = {
        provider: document.getElementById('imageProvider').value,
        api_key: document.getElementById('imageApiKey').value,
        base_url: document.getElementById('imageBaseUrl').value,
        model_name: modelName,
        temperature: parseFloat(document.getElementById('imageTemperature').value),
        is_enabled: document.getElementById('imageEnabled').checked
    };

    // Azure 特有配置
    if (config.provider === 'azure') {
        config.endpoint = document.getElementById('imageEndpoint').value;
        config.api_version = document.getElementById('imageApiVersion').value;
    }

    console.log('[Image Config] 准备保存配置:', {
        provider: config.provider,
        api_key: config.api_key ? `${config.api_key.substring(0, 15)}...` : '(空)',
        base_url: config.base_url,
        model_name: config.model_name,
        is_enabled: config.is_enabled
    });

    try {
        // 1. 保存配置
        console.log('[Image Config] 发送保存请求...');
        const saveResponse = await fetch('/api/v1/config/image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const saveResult = await saveResponse.json();
        console.log('[Image Config] 保存响应:', saveResult);

        if (saveResult.status !== 'success') {
            throw new Error(saveResult.message);
        }

        console.log('[Image Config] ✅ 配置保存成功');

        // 2. 热重载配置
        console.log('[Image Config] 开始热重载配置...');
        const reloadResponse = await fetch('/api/v1/config/image/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();
        console.log('[Image Config] 热重载响应:', reloadResult);

        if (reloadResult.status === 'success') {
            const reloadConfig = reloadResult.config || {};
            const sourceText = reloadConfig.enabled ? '用户自定义' : '.env 默认';
            console.log('[Image Config] ✅ 配置已重载:', reloadConfig);

            alert(`✅ 配置已保存并应用！\n\n当前配置：${sourceText}\n模型：${reloadConfig.model || config.model_name}`);
        } else {
            throw new Error(reloadResult.message);
        }
    } catch (error) {
        console.error('[Image Config] ❌ 保存失败:', error);
        alert('❌ 操作失败: ' + error.message);
    }
}

async function resetImageConfig() {
    if (!confirm('确定要切换回 .env 配置吗？\n\n这将禁用所有自定义配置，系统将使用 .env 文件中的环境变量。')) {
        return;
    }

    try {
        // 1. 调用重置端点
        const resetResponse = await fetch('/api/v1/config/image/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const resetResult = await resetResponse.json();

        if (resetResult.status !== 'success') {
            throw new Error(resetResult.message || '重置失败');
        }

        // 2. 热重载配置
        const reloadResponse = await fetch('/api/v1/config/image/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            const reloadConfig = reloadResult.config || {};
            console.log('[Image Config] 已重置为 .env 配置:', reloadConfig);

            // 3. 更新UI状态
            document.getElementById('imageEnabled').checked = false;
            document.getElementById('imageConfigForm').classList.add('hidden');

            alert('✅ 已切换到 .env 配置！\n\n模型：' + (reloadConfig.model || 'gpt-4-vision'));
        } else {
            throw new Error(reloadResult.message || '重载失败');
        }
    } catch (error) {
        console.error('[Image Config Reset Error]', error);
        alert('❌ 切换失败: ' + error.message);
    }
}

document.addEventListener('DOMContentLoaded', initImageConfig);
