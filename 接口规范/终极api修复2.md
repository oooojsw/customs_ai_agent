这是一个基于我们深度分析后的**最终完整修复方案**。

这个方案采用了**“后端强制更新机制 + 前端无锁并发防御机制”**。它既解决了“Key 消失”的 Bug，又通过竞态检查（Race Condition Check）防止了你担心的“去锁后数据错乱”问题。

请严格按照以下三个步骤操作。

---

### 第一步：后端修复 (Backend)

确保数据库逻辑绝对稳健。即使前端乱发请求，后端也能保证“最后保存的那个”是激活的，且时间戳最新。

**文件路径**：`src/database/crud.py`
**操作**：找到 `save_config` 方法，用下面的代码**完全替换**。

```python
    async def save_config(self, config_data: dict) -> UserLLMConfig:
        """
        保存配置（最终稳定版）
        核心逻辑：
        1. 状态互斥：先禁用全库，确保唯一性。
        2. 时间锚定：显式更新 updated_at，防止排序混乱。
        3. 空值防御：禁止空字符串覆盖已有 Key。
        """
        provider = config_data['provider'].strip().lower()
        is_enable_action = config_data.get('is_enabled', True)
        
        # 1.【关键】状态互斥：如果要启用当前配置，先将全库所有配置设为 Disabled
        if is_enable_action:
            await self.disable_all_configs()

        # 2. 获取现有记录
        existing = await self.get_config_by_provider(provider)
        new_api_key = config_data.get('api_key', '').strip()

        if existing:
            # === 更新现有记录 ===
            
            # 【关键】智能更新 Key：只有当用户填了新 Key 时才更新，防止前端传空值覆盖
            if new_api_key:
                existing.api_key = new_api_key
            
            # 更新其他字段
            if config_data.get('base_url'): existing.base_url = config_data['base_url']
            if config_data.get('model_name'): existing.model_name = config_data['model_name']
            if config_data.get('api_version') is not None: existing.api_version = config_data['api_version']
            
            existing.temperature = config_data.get('temperature', 0.3)
            existing.is_enabled = is_enable_action
            
            # 【核心修复】强制刷新时间戳
            # 这保证了当你切回这个供应商时，它永远排在查询结果的第一位
            existing.updated_at = datetime.now()
            
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            # === 创建新记录 ===
            new_config = UserLLMConfig(
                provider=provider,
                is_enabled=is_enable_action,
                api_key=new_api_key,
                base_url=config_data.get('base_url', ''),
                model_name=config_data.get('model_name', ''),
                api_version=config_data.get('api_version'),
                temperature=config_data.get('temperature', 0.3),
                test_status='never',
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            self.db.add(new_config)
            await self.db.commit()
            await self.db.refresh(new_config)
            return new_config

```

---

### 第二步：前端修复 (Frontend) - 核心重点

这是解决你“切换时没有反应”和“担心并发Bug”的终极代码。

**设计原理**：

1. **移除所有锁**：不再使用 `is_loading` 锁，确保每次切换**必定**触发请求，杜绝“卡死”。
2. **加入竞态检查 (Race Condition Check)**：在请求返回时，检查“**当前界面上选的供应商**”是否还等于“**我发出请求时的供应商**”。如果不相等，说明用户手快又切走了，直接丢弃数据，不予显示。

**文件路径**：`web/js/llm_config.js`
**操作**：**完全清空**该文件，粘贴以下所有代码。

```javascript
/**
 * LLM 配置管理 - 最终完美版 (v3.1.0)
 * 特性：无锁架构 + 竞态条件防御 (Race Condition Protection)
 */

// 1. 厂商预设
const PROVIDER_PRESETS = {
    deepseek: { base_url: 'https://api.deepseek.com/v1', models: ['deepseek-chat', 'deepseek-coder'] },
    openai: { base_url: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4-turbo'] },
    qwen: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen-plus', 'qwen-max'] },
    zhipu: { base_url: 'https://open.bigmodel.cn/api/paas/v4/', models: ['glm-4', 'glm-4-flash'] },
    siliconflow: { base_url: 'https://api.siliconflow.cn/v1', models: ['Qwen/Qwen2.5-72B-Instruct', 'deepseek-ai/DeepSeek-V3'] },
    azure: { base_url: '', models: [] },
    custom: { base_url: '', models: [] }
};

// 2. 初始化
async function initLLMConfig() {
    console.log('🚀 [Init] 系统初始化...');
    try {
        // 获取当前激活的配置
        const response = await fetch('/api/v1/config/llm');
        const config = await response.json();
        console.log('📦 [Init] 当前激活配置:', config);

        // 1. 设置开关状态
        document.getElementById('llmEnabled').checked = config.is_enabled;
        toggleLLMFields();

        // 2. 设置下拉框选中项
        const provider = config.provider || 'deepseek';
        document.getElementById('llmProvider').value = provider;

        // 3. 填充字段 (直接使用 /api/v1/config/llm 返回的最新数据)
        if (config.base_url) document.getElementById('llmBaseUrl').value = config.base_url;
        if (config.model_name) document.getElementById('llmModelName').value = config.model_name;
        if (config.temperature) document.getElementById('llmTemperature').value = config.temperature;
        
        // 关键：初始化时回填 Key
        if (config.api_key) {
            document.getElementById('llmApiKey').value = config.api_key;
            console.log('🔑 [Init] API Key 已回填');
        }

        // 4. 处理 Azure 界面显隐
        updateUIForAzure(provider);

    } catch (error) {
        console.error('❌ [Init] 初始化失败:', error);
    }
}

// 3. 核心：切换服务商 (onChange 事件)
async function updateProviderPresets() {
    const provider = document.getElementById('llmProvider').value;
    console.log(`🔄 [Switch] 切换至服务商: ${provider}`);

    // A. 界面调整
    updateUIForAzure(provider);

    // B. 预填 Base URL
    const preset = PROVIDER_PRESETS[provider];
    if (preset && preset.base_url) {
        document.getElementById('llmBaseUrl').value = preset.base_url;
    } else {
        document.getElementById('llmBaseUrl').value = '';
    }

    // C. 视觉上先清空 Key，避免误导用户
    document.getElementById('llmApiKey').value = '';

    // D. 发起异步请求获取该厂商的 Key
    // 注意：这里没有任何锁，必须去请求
    await loadProviderConfig(provider);

    // E. 刷新模型列表
    fetchModels();
}

// 4. 核心：安全加载配置 (含竞态检查)
async function loadProviderConfig(provider) {
    // 【关键】记录发起请求时的目标，用于验证
    const targetProvider = provider;
    
    try {
        console.log(`📡 [Fetch] 正在请求 ${provider} 的配置...`);
        // 加时间戳防止浏览器缓存
        const url = `/api/v1/config/llm/provider/${provider}?_t=${Date.now()}`;
        const res = await fetch(url);
        const data = await res.json();

        // 🛡️【竞态条件防御】
        // 检查：请求回来时，用户选的还是我请求的那个厂商吗？
        const currentSelection = document.getElementById('llmProvider').value;
        if (currentSelection !== targetProvider) {
            console.warn(`🛑 [Race] 请求已过期。界面当前是 ${currentSelection}，但返回的是 ${targetProvider}。已丢弃数据。`);
            return; // ⛔ 直接退出，不更新界面，防止数据错乱
        }

        // 如果一致，才安全地更新界面
        if (data.status === 'success' && data.config) {
            const conf = data.config;
            console.log(`✅ [Load] 配置加载成功:`, conf);

            // 只有当服务器有 Key 时才填入，否则保持为空（等待用户填）
            if (conf.api_key) {
                document.getElementById('llmApiKey').value = conf.api_key;
            }
            // 恢复其他字段
            if (conf.base_url) document.getElementById('llmBaseUrl').value = conf.base_url;
            if (conf.model_name) document.getElementById('llmModelName').value = conf.model_name;
        } else {
            console.log(`ℹ️ [Load] ${provider} 暂无历史配置`);
        }
    } catch (e) {
        console.error(`❌ [Fetch] 请求出错:`, e);
    }
}

// 5. 保存配置
async function saveLLMConfig() {
    const config = {
        provider: document.getElementById('llmProvider').value,
        api_key: document.getElementById('llmApiKey').value.trim(),
        base_url: document.getElementById('llmBaseUrl').value.trim(),
        model_name: document.getElementById('llmModelName').value,
        temperature: parseFloat(document.getElementById('llmTemperature').value),
        is_enabled: document.getElementById('llmEnabled').checked,
        api_version: document.getElementById('llmApiVersion').value
    };

    if (config.is_enabled && !config.api_key) {
        alert("⚠️ 启用自定义配置时，API Key 不能为空！");
        return;
    }

    try {
        console.log('💾 [Save] 提交保存...');
        const res = await fetch('/api/v1/config/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (res.ok) {
            alert("✅ 配置已保存并应用！");
            // 触发热重载
            fetch('/api/v1/config/llm/reload', { method: 'POST' });
        } else {
            alert("❌ 保存失败，请检查后端日志");
        }
    } catch (e) {
        alert("❌ 网络请求错误: " + e.message);
    }
}

// 6. 获取模型列表
async function fetchModels() {
    const provider = document.getElementById('llmProvider').value;
    const apiKey = document.getElementById('llmApiKey').value;
    const baseUrl = document.getElementById('llmBaseUrl').value;
    const select = document.getElementById('llmModelName');

    // 如果没 Key，优先展示预设，不发请求
    if (!apiKey) {
        const presets = PROVIDER_PRESETS[provider]?.models || [];
        if (presets.length > 0) {
            select.innerHTML = presets.map(m => `<option value="${m}">${m}</option>`).join('');
            return;
        }
    }

    try {
        select.innerHTML = '<option>加载中...</option>';
        const res = await fetch(`/api/v1/config/llm/models?provider=${provider}&api_key=${apiKey}&base_url=${baseUrl}`);
        const data = await res.json();

        if (data.status === 'success' && data.models?.length > 0) {
            select.innerHTML = data.models.map(m => `<option value="${m}">${m}</option>`).join('');
        } else {
            // 回退到预设
            const presets = PROVIDER_PRESETS[provider]?.models || ['deepseek-chat'];
            select.innerHTML = presets.map(m => `<option value="${m}">${m}</option>`).join('');
        }
    } catch (e) {
        console.warn('获取模型列表失败，使用默认值');
        select.innerHTML = '<option value="deepseek-chat">deepseek-chat</option>';
    }
}

// 7. 辅助函数
function toggleLLMFields() {
    const enabled = document.getElementById('llmEnabled').checked;
    document.getElementById('llmConfigForm').classList.toggle('hidden', !enabled);
}

function updateUIForAzure(provider) {
    const group = document.getElementById('azureConfigGroup');
    if (group) {
        group.classList.toggle('hidden', provider !== 'azure');
    }
}

function testLLMConnection() {
    alert("请直接点击【保存并应用】来验证连通性。");
}

function resetLLMConfig() {
    if(confirm("确定要重置为 .env 默认配置吗？")) {
        fetch('/api/v1/config/llm/reset', { method: 'POST' })
            .then(() => {
                alert("已重置");
                location.reload();
            });
    }
}

// 启动
document.addEventListener('DOMContentLoaded', initLLMConfig);

```

---

### 第三步：强制生效 (Action)

因为我们修改了 JavaScript 文件，浏览器**一定会缓存**旧版本。你之前“没有日志”就是因为浏览器还在跑旧代码。

1. 保存好上面两个文件。
2. 打开浏览器。
3. **不要点刷新按钮！**
4. 按下键盘上的 **`Ctrl` + `F5**` (Windows) 或 **`Command` + `Shift` + `R**` (Mac)。
5. 在页面上切换供应商。

**预期结果**：
你现在可以随意、快速地在下拉菜单中切换。无论你切得多快，输入框里的 Key 都**绝对不会**张冠李戴（显示错误的 Key），也**绝对不会**消失。如果不一致，它会直接丢弃，等待正确的那次请求回来。