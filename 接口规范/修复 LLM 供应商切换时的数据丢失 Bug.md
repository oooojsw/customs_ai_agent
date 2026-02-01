通过对你提供的全量代码（尤其是 src/database/crud.py 和 web/js/llm_config.js）进行“像素级”审计，我发现了问题的根源。

这是一个典型的**“前端清除逻辑”与“后端全量覆盖”**之间的协同 Bug。

🔍 深度原因分析：为什么 Key 丢了？
1. 前端：切换时的“自杀式”清空

在 web/js/llm_config.js 的 updateProviderPresets() 函数中（约 150-160 行）：

当用户在下拉框选择“供应商2”时，前端为了防止“供应商1”的 Key 残留在输入框里，执行了：document.getElementById('llmApiKey').value = '';。

此时，UI 上的 API Key 变成了空字符串。

2. 后端：无差别的“暴力更新”逻辑

在 src/database/crud.py 的 save_config 方法中（约 175-185 行）：

后端逻辑是：existing.api_key = config_data['api_key']。

它并没有判断 api_key 是否为空。只要前端传了，它就存。

致命路径：用户切换厂商 -> 前端清空输入框 -> 某些操作触发了“保存/自动保存” -> 前端把“空字符串”发给后端 -> 后端把数据库里该厂商原本存好的 Key 覆盖成了空。

3. 异步加载的“时间差”

虽然前端有 loadProviderConfig(provider) 来尝试从数据库读取旧 Key，但这是一个异步请求。

如果在旧 Key 还没加载回来之前，用户点击了“保存”，或者触发了某些 onblur 自动保存逻辑，空值就会瞬间杀死数据库里的旧值。

🛠️ 像素级修复规范：数据原子性保护方案

请将以下规范交给 Cursor，要求其进行“非破坏性更新”重构。

📑 任务指令书：修复 LLM 供应商切换时的数据丢失 Bug
1. 后端 CRUD 逻辑重构 (Service Layer Fix)

文件：src/database/crud.py
目标：将 save_config 改造为“增量/非空”更新模式。
指令：

修改 LLMConfigRepository.save_config 方法。

核心逻辑更新：在更新 existing 记录时，必须增加判断：只有当 config_data 中的字段非空且不为 None 时，才执行赋值操作。

伪逻辑参考：

如果 config_data.get('api_key') 是空字符串且数据库里已经有值，严禁覆盖，保持原值。

同样的处理逻辑应应用于 base_url 和 model_name。

理由：确保前端在切换 UI 状态或加载未完成时发送的空数据不会破坏数据库中的持久化数据。

2. 前端切换逻辑优化 (UI/UX Logic Fix)

文件：web/js/llm_config.js
目标：防止加载过程中的“无效覆盖”。
指令：

修改 updateProviderPresets() 函数。

引入 Loading 锁：在执行 loadProviderConfig(provider) 期间，将“保存并应用”按钮设为 disabled 状态。

UI 清理策略：在清空 llmApiKey 输入框时，添加一个标志位 is_loading_config = true。

修改 getFormConfig()：如果 is_loading_config 为 true，拒绝提取数据，防止提取到中间状态的空值。

3. 数据库模型验证 (Model Constraint)

文件：src/database/models.py
目标：从底层防止脏数据。
指令：

确保 UserLLMConfig 表中的 api_key 字段在数据库层面虽然允许为空（为了初始化），但业务逻辑层应确保“已启用（is_enabled=True）”的配置必须包含有效的 api_key。

4. 验收测试场景 (Validation)

请创建测试脚本验证以下流程：

保存供应商 A 的 Key。

切换到供应商 B，不填任何东西。

点击“保存”。

切换回供应商 A。

预期结果：供应商 A 的 Key 必须依然存在，不能被步骤 3 的操作抹除。

💡 给 Cursor 的专家建议（必读）

“目前的 Bug 是因为你使用了全量覆盖逻辑。在处理多厂商配置切换时，前端的‘清空输入框’动作被后端误解为‘用户想删除这个 Key’。请务必实现 Patch (局部更新) 逻辑，即：if new_value: existing.value = new_value。只有用户在 UI 上明确输入了内容并保存时，才更新数据库。”

通过这个“Patch 更新”机制，你的供应商切换将变得无比丝滑，再也不会丢失已经填好的 API Key 了。