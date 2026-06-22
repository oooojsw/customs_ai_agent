// ==========================================
// 1. 图像独立状态缓存
// ==========================================
const imageStateCache = {};

// ==========================================
// 2. 实时监听图像输入
// ==========================================
let imageFetchModelsTimeout = null;

function setupImageInputListeners() {
    const inputMapping = {
        'imageApiKey': 'apiKey',
        'imageBaseUrl': 'baseUrl',
        'imageModelName': 'modelName',
        'imageTemperature': 'temperature',
        'imageEndpoint': 'endpoint',
        'imageApiVersion': 'apiVersion'
    };

    Object.keys(inputMapping).forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', (e) => {
                const provider = document.getElementById('imageProvider').value;
                if (!imageStateCache[provider]) {
                    imageStateCache[provider] = {};
                }
                const cacheKey = inputMapping[id];
                imageStateCache[provider][cacheKey] = e.target.value;

                // API Key 输入后自动加载模型（防抖处理）
                if (id === 'imageApiKey' && typeof fetchImageModels === 'function') {
                    clearTimeout(imageFetchModelsTimeout);
                    imageFetchModelsTimeout = setTimeout(() => {
                        fetchImageModels();
                    }, 800);
                }
            });
        }
    });
}

// ==========================================
// 3. 统一渲染图像 UI
// ==========================================
function renderImageForm(provider) {
    const state = imageStateCache[provider] || {};
    const preset = (typeof PROVIDER_PRESETS !== 'undefined' ? PROVIDER_PRESETS[provider] : {}) || {};
    
    const apiKeyInput = document.getElementById('imageApiKey');
    apiKeyInput.value = state.apiKey || '';
    apiKeyInput.placeholder = state.hasApiKey
        ? '已保存，留空则保留原密钥'
        : '请输入 API Key';
    document.getElementById('imageBaseUrl').value = state.baseUrl || preset.base_url || '';
    
    const modelSelect = document.getElementById('imageModelName');
    if (state.modelName) {
        if (!Array.from(modelSelect.options).some(opt => opt.value === state.modelName)) {
            modelSelect.add(new Option(state.modelName, state.modelName));
        }
        modelSelect.value = state.modelName;
    } else {
        modelSelect.innerHTML = '<option value="">请选择服务商后点击刷新按钮</option>';
    }
    
    if (state.temperature !== undefined) {
        document.getElementById('imageTemperature').value = state.temperature;
        const tempValue = document.getElementById('imageTempValue');
        if (tempValue) tempValue.innerText = state.temperature;
    }
    
    const endpointEl = document.getElementById('imageEndpoint');
    const apiVersionEl = document.getElementById('imageApiVersion');
    if (endpointEl && state.endpoint !== undefined) endpointEl.value = state.endpoint;
    if (apiVersionEl && state.apiVersion !== undefined) apiVersionEl.value = state.apiVersion;
}

// ==========================================
// 4. 从后端安全拉取图像配置
// ==========================================
async function fetchImageProviderConfigFromDB(provider) {
    try {
        const response = await fetch(`/api/v1/config/image/provider/${provider}?_t=${Date.now()}`);
        const result = await response.json();
        
        const preset = (typeof PROVIDER_PRESETS !== 'undefined' ? PROVIDER_PRESETS[provider] : {}) || {};

        if (result.status === 'success' && result.config) {
            const config = result.config;
            
            imageStateCache[provider] = {
                apiKey: '',
                hasApiKey: Boolean(config.has_api_key),
                baseUrl: config.base_url || preset.base_url || '',
                modelName: config.model_name || '',
                temperature: config.temperature !== undefined ? config.temperature : 0.1,
                endpoint: config.endpoint || '',
                apiVersion: config.api_version || ''
            };
        } else {
            imageStateCache[provider] = { 
                apiKey: '', 
                baseUrl: preset.base_url || '', 
                temperature: 0.1 
            };
        }
    } catch (error) {
        console.error(`[Image Config] ${provider} 加载失败`, error);
        imageStateCache[provider] = { apiKey: '', baseUrl: '' };
    }
}

// ==========================================
// 5. 核心：图像切换厂商逻辑
// ==========================================
async function updateImageProviderPresets() {
    const provider = document.getElementById('imageProvider').value;
    const azureGroup = document.getElementById('imageAzureGroup');
    
    if (provider === 'azure') {
        azureGroup.classList.remove('hidden');
    } else {
        azureGroup.classList.add('hidden');
    }

    if (!imageStateCache[provider]) {
        const apiKeyInput = document.getElementById('imageApiKey');
        apiKeyInput.value = '';
        apiKeyInput.placeholder = '正在从服务器加载配置...';
        
        await fetchImageProviderConfigFromDB(provider);
        
        apiKeyInput.placeholder = '请输入 API Key';
    }

    renderImageForm(provider);
    
    if (typeof fetchImageModels === 'function') {
        fetchImageModels();
    }
}

// ==========================================
// 6. 图像初始化重构
// ==========================================
async function initImageConfig() {
    setupImageInputListeners();

    try {
        const response = await fetch('/api/v1/config/image');
        const config = await response.json();

        document.getElementById('imageEnabled').checked = config.is_enabled;
        const provider = config.provider || 'azure';
        document.getElementById('imageProvider').value = provider;
        
        imageStateCache[provider] = {
            apiKey: '',
            hasApiKey: Boolean(config.has_api_key),
            baseUrl: config.base_url || '',
            modelName: config.model_name || '',
            temperature: config.temperature !== undefined ? config.temperature : 0.1,
            endpoint: config.endpoint || '',
            apiVersion: config.api_version || ''
        };

        const azureGroup = document.getElementById('imageAzureGroup');
        if (provider === 'azure') {
            azureGroup.classList.remove('hidden');
        } else {
            azureGroup.classList.add('hidden');
        }

        renderImageForm(provider);
        if (typeof toggleImageFields === 'function') toggleImageFields();
        
    } catch (error) {
        console.error('[Image Config] 加载配置失败:', error);
    }
}

// ==========================================
// 7. 辅助函数
// ==========================================
function toggleImageFields() {
    const enabled = document.getElementById('imageEnabled').checked;
    const form = document.getElementById('imageConfigForm');
    form.classList.toggle('hidden', !enabled);
}

async function fetchImageModels() {
    const provider = document.getElementById('imageProvider').value;
    const apiKey = document.getElementById('imageApiKey').value;
    const baseUrl = document.getElementById('imageBaseUrl').value;
    const apiVersion = document.getElementById('imageApiVersion')?.value || '2024-03-01-preview';
    const modelSelect = document.getElementById('imageModelName');

    modelSelect.innerHTML = '<option value="">正在获取模型列表...</option>';

    try {
        let models = [];

        // 智谱GLM
        if (provider === 'zhipu') {
            models = PROVIDER_PRESETS.zhipu.models;
        } else if (provider === 'azure') {
            if (!apiKey || !baseUrl) {
                modelSelect.innerHTML = '<option value="">Azure需要 API Key 和 Endpoint</option>';
                return;
            }
            const response = await fetch('/api/v1/config/image/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider,
                    api_key: apiKey,
                    base_url: baseUrl,
                    api_version: apiVersion
                })
            });
            const result = await response.json();
            if (result.status === 'success') {
                models = result.models;
            } else {
                modelSelect.innerHTML = `<option value="">${result.message}</option>`;
                return;
            }
        } else {
            if (!apiKey) {
                const presetModels = PROVIDER_PRESETS[provider]?.models;
                if (presetModels && presetModels.length > 0) {
                    models = presetModels;
                } else {
                    modelSelect.innerHTML = '<option value="">请先输入 API Key</option>';
                    return;
                }
            } else {
                const response = await fetch('/api/v1/config/image/models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        provider,
                        api_key: apiKey,
                        base_url: (
                            baseUrl && (provider === 'custom' || provider === 'siliconflow')
                                ? baseUrl
                                : null
                        )
                    })
                });
                const result = await response.json();
                if (result.status === 'success') {
                    models = result.models;
                } else {
                    modelSelect.innerHTML = `<option value="">${result.message}</option>`;
                    return;
                }
            }
        }

        if (models.length > 0) {
            modelSelect.innerHTML = models.map(model =>
                `<option value="${model}">${model}</option>`
            ).join('');
            modelSelect.value = models[0];
        } else {
            modelSelect.innerHTML = '<option value="">未找到可用模型</option>';
        }
    } catch (error) {
        console.error('获取模型列表失败:', error);
        modelSelect.innerHTML = '<option value="">获取失败，请稍后重试</option>';
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
    const provider = document.getElementById('imageProvider').value;
    const apiKey = document.getElementById('imageApiKey').value.trim();
    const isEnabled = document.getElementById('imageEnabled').checked;
    const modelName = document.getElementById('imageModelName').value;
    const hasSavedKey = Boolean(imageStateCache[provider]?.hasApiKey);

    if (isEnabled && !apiKey && !hasSavedKey) {
        alert("⚠️ API Key 不能为空！");
        return;
    }

    if (apiKey && apiKey.length < 10) {
        alert("⚠️ API Key 格式不正确");
        return;
    }

    if (!modelName) {
        alert('❌ 请先点击刷新按钮获取模型列表');
        return;
    }

    const config = {
        provider: provider,
        api_key: apiKey,
        base_url: document.getElementById('imageBaseUrl').value,
        model_name: modelName,
        temperature: parseFloat(document.getElementById('imageTemperature').value),
        is_enabled: isEnabled
    };

    if (config.provider === 'azure') {
        config.endpoint = document.getElementById('imageEndpoint').value;
        config.api_version = document.getElementById('imageApiVersion').value;
    }

    try {
        const saveResponse = await fetch('/api/v1/config/image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const saveResult = await saveResponse.json();

        if (saveResult.status !== 'success') {
            throw new Error(saveResult.message);
        }
        if (!imageStateCache[provider]) imageStateCache[provider] = {};
        imageStateCache[provider].hasApiKey = hasSavedKey || Boolean(apiKey);
        imageStateCache[provider].apiKey = '';
        renderImageForm(provider);

        const reloadResponse = await fetch('/api/v1/config/image/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            alert(`✅ 配置已保存并应用！`);
        } else {
            throw new Error(reloadResult.message);
        }
    } catch (error) {
        alert('❌ 操作失败: ' + error.message);
    }
}

async function resetImageConfig() {
    if (!confirm('确定要切换回 .env 配置吗？')) {
        return;
    }

    try {
        const resetResponse = await fetch('/api/v1/config/image/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const resetResult = await resetResponse.json();

        if (resetResult.status !== 'success') {
            throw new Error(resetResult.message);
        }

        const reloadResponse = await fetch('/api/v1/config/image/reload', {
            method: 'POST'
        });

        const reloadResult = await reloadResponse.json();

        if (reloadResult.status === 'success') {
            document.getElementById('imageEnabled').checked = false;
            document.getElementById('imageConfigForm').classList.add('hidden');
            alert('✅ 已切换到 .env 配置！');
        } else {
            throw new Error(reloadResult.message);
        }
    } catch (error) {
        alert('❌ 切换失败: ' + error.message);
    }
}

// ==========================================
// 启动
// ==========================================
document.addEventListener('DOMContentLoaded', initImageConfig);

// 暴露全局函数
window.toggleImageFields = toggleImageFields;
window.updateImageProviderPresets = updateImageProviderPresets;
window.saveImageConfig = saveImageConfig;
window.fetchImageModels = fetchImageModels;
window.testImageConnection = testImageConnection;
window.resetImageConfig = resetImageConfig;
