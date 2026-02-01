通过仔细审查你刚刚上传的代码 `_COLLECTED_CODE_20260202_055331.txt`，特别是 `src/database/crud.py` 中的 `save_config` 方法，我发现你虽然加上了 `disable_all_configs()`，但还有**两个关键隐患**可能导致了“Key 消失”的现象。

以下是补充的重要信息和修复建议：

### 1. 致命隐患：时间戳未显式更新导致排序错乱

在你的代码中，`UserLLMConfig` 模型定义了 `updated_at` 字段：

```python
updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

```

虽然数据库通常会自动更新这个字段，但在 `save_config` 函数中，当你执行 `await self.disable_all_configs()` 时，它会批量更新**所有**配置（将它们设为 Disabled），这会导致所有旧记录的 `updated_at` 时间戳同时被刷新。

**问题场景复现：**

1. 你保存了 **Provider 2**（设为启用）。`disable_all_configs` 运行，把 **Provider 1** 设为禁用。
2. 此时，**Provider 1** 和 **Provider 2** 的 `updated_at` 时间几乎完全相同（毫秒级差异）。
3. 当你切换回 **Provider 1** 时，系统调用 `get_config_by_provider`：
```python
stmt = select(UserLLMConfig)...order_by(UserLLMConfig.updated_at.desc()).limit(1)

```


4. 如果数据库中存在多条 **Provider 1** 的历史记录（比如一条有 Key，一条是空的），且由于批量更新导致时间戳过于接近，数据库排序可能会变得不稳定，或者“空记录”恰好排在了“有 Key 记录”的前面。

**补充修复：** 必须在代码中**显式**更新当前正在保存的记录的时间戳，使其绝对晚于 `disable_all_configs` 造成的时间戳。

### 2. 前端数据获取逻辑的潜在冲突

如果在前端切换下拉菜单时，Key 输入框被清空，除了后端排序问题，还可能是前端获取数据的接口用错了。

* **错误场景**：前端可能在切换时调用了 `/api/v1/config/llm`（获取当前**激活**的配置）。如果你刚保存了 Provider 2（激活），然后切换下拉框到 Provider 1（此时已禁用），如果前端逻辑是“获取激活配置”，它拿到的其实还是 Provider 2 的数据，或者因为 Provider 1 不是激活状态而拿到空值。
* **正确场景**：前端必须调用 `/api/v1/config/llm/provider/{provider_name}` 来获取特定供应商的配置。

**建议自查：** 请打开浏览器控制台 (F12) -> Network，当你切换回 Provider 1 时，观察请求的响应内容。如果响应里有 `api_key` 但界面没显示，那就是前端 JS 判断了 `is_enabled=false` 导致隐藏；如果响应里 `api_key` 是空的，那就是后端排序/数据覆盖问题。

---

### 最终完整代码修正 (CRUD)

建议用下面的代码**完全替换** `src/database/crud.py` 中的 `save_config` 方法。这个版本加入了显式时间戳更新，并优化了事务提交顺序，能彻底解决“Key 消失”的后端因素。

```python
    async def save_config(self, config_data: dict) -> UserLLMConfig:
        """
        保存配置（最终增强版：解决状态互斥 + 时间戳排序 + 数据丢失问题）
        """
        provider = config_data['provider']
        
        # 1. 状态互斥：如果要启用当前配置，先禁用全库所有配置
        # 移到最前面执行，防止后续操作被它的批量更新覆盖时间戳
        if config_data.get('is_enabled', True):
            await self.disable_all_configs()

        # 2. 重新获取配置（确保拿到最新状态）
        existing = await self.get_config_by_provider(provider)

        if existing:
            # === 增量更新保护 ===
            # 只有当前端传来的值不为空时才更新，防止前端传空字符串覆盖掉数据库里的 Key
            if config_data.get('api_key'):
                existing.api_key = config_data['api_key']
            
            if config_data.get('base_url'):
                existing.base_url = config_data['base_url']
                
            if config_data.get('model_name'):
                existing.model_name = config_data['model_name']
                
            if config_data.get('api_version') is not None: # 允许清除 api_version
                existing.api_version = config_data['api_version']
            
            # 数值类型直接更新
            existing.temperature = config_data.get('temperature', 0.3)
            existing.test_status = 'never'
            
            # === 关键修复：强制更新时间戳 ===
            # 确保这条记录的时间戳绝对晚于 disable_all_configs 的时间戳
            # 这样 get_config_by_provider 的 order_by(desc) 才能稳定返回这一条
            existing.updated_at = datetime.now()
            
            # 更新启用状态
            existing.is_enabled = config_data.get('is_enabled', True)
            
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            # === 创建新记录 ===
            new_config = UserLLMConfig(
                provider=provider,
                is_enabled=config_data.get('is_enabled', True),
                api_key=config_data.get('api_key', ''),
                base_url=config_data.get('base_url', ''),
                model_name=config_data.get('model_name', ''),
                api_version=config_data.get('api_version'),
                temperature=config_data.get('temperature', 0.3),
                test_status='never',
                # 显式初始化时间
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            self.db.add(new_config)
            await self.db.commit()
            await self.db.refresh(new_config)
            return new_config

```






这个问题很可能不是简单的“状态没更新”，而是**前端显示逻辑**和**后端数据排序**的隐性冲突。

### 核心原因分析

1. **后端逻辑**：`save_config` 中的 `disable_all_configs` 会将 Provider 1 设为 `is_enabled=False`。
2. **前端行为（推测）**：当你在界面上切换回 Provider 1 时，前端发现这个配置是 **Disabled**（未启用）状态，某些前端逻辑可能会**默认清空输入框**或者认为“未配置”，导致你看不到原来的 Key。
3. **排序隐患**：`get_config_by_provider` 是按 `updated_at` 倒序取最新的。如果你在数据库中对同一个 Provider 有多条记录（例如一条有 Key，一条没 Key），当你保存 Provider 2 时，Provider 1 被禁用并**更新了时间**。如果这个操作让一个“空 Key”的旧记录浮上来（虽然概率较小，但取决于更新逻辑），或者仅仅是因为被禁用导致查询逻辑变化，都会导致数据“丢失”的假象。

### 彻底修复方案

你需要重构 `src/database/crud.py` 中的 `save_config` 方法。

**改进点：**

1. **前置互斥操作**：将 `disable_all_configs()` 移到最前面执行，避免事务提交顺序导致的混乱。
2. **强制时间更新**：显式更新 `updated_at` 时间，确保当前保存的配置永远是数据库里“最新”的，防止 `get_config_by_provider` 查到旧的空记录。
3. **防御性编程**：在获取 `existing` 后再次确认，防止并发问题。

请使用以下代码**完全替换** `src/database/crud.py` 中的 `save_config` 方法：

```python
    async def save_config(self, config_data: dict) -> UserLLMConfig:
        """
        保存配置（增强版：解决状态切换导致的数据丢失假象）
        """
        provider = config_data['provider']
        
        # === 步骤 1: 状态互斥 ===
        # 如果当前操作是"启用"，先禁用全库所有配置。
        # 移到最前面执行，确保环境干净，防止后续操作被覆盖。
        if config_data.get('is_enabled', True):
            await self.disable_all_configs()

        # === 步骤 2: 重新获取配置 ===
        # 注意：disable_all_configs 提交了事务，建议重新获取对象以确保状态最新
        existing = await self.get_config_by_provider(provider)

        if existing:
            # === 步骤 3: 增量更新 ===
            # 只有当新值存在且不为空时才覆盖，防止前端传空值导致 Key 丢失
            if config_data.get('api_key'):
                existing.api_key = config_data['api_key']
            if config_data.get('base_url'):
                existing.base_url = config_data['base_url']
            if config_data.get('model_name'):
                existing.model_name = config_data['model_name']
            if config_data.get('api_version'):
                existing.api_version = config_data['api_version']
            
            # 数值型字段直接更新
            existing.temperature = config_data.get('temperature', 0.3)
            existing.test_status = 'never'
            
            # === 关键修复: 强制更新时间戳 ===
            # 确保这条记录在 get_config_by_provider 排序中永远排在第一位
            # 防止数据库中存在多条同厂商记录时，取到了旧的空记录
            existing.updated_at = datetime.now()
            
            # 设置启用状态
            existing.is_enabled = config_data.get('is_enabled', True)
            
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            # === 步骤 4: 创建新记录 ===
            new_config = UserLLMConfig(
                provider=provider,
                is_enabled=config_data.get('is_enabled', True),
                api_key=config_data['api_key'],
                base_url=config_data['base_url'],
                model_name=config_data['model_name'],
                api_version=config_data.get('api_version'),
                temperature=config_data.get('temperature', 0.3),
                test_status='never',
                # 显式设置时间
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            self.db.add(new_config)
            await self.db.commit()
            await self.db.refresh(new_config)
            return new_config

```

### 为什么这次能解决？

1. **显式 `updated_at = datetime.now()**`：
这是最关键的一步。`get_config_by_provider` 是通过 `order_by(updated_at.desc())` 获取数据的。当你保存 Provider 2 时，Provider 2 变新了。当你切回 Provider 1 时，如果你之前的 Provider 1 记录没有被显式更新时间，且数据库里碰巧有一条**空的** Provider 1 记录（比如之前测试留下的）时间更新一点，系统就会加载那条空的，导致你觉得“Key 不见了”。强制更新时间能确保你正在操作的这条记录永远是“最新”的。
2. **防止 Key 被清空**：
代码保留了 `if config_data.get('api_key'):` 判断。这意味着如果前端因为 Bug 传了一个空 Key 过来，后端会**拒绝更新** Key，从而保护数据库里原有的 Key 不被覆盖。

**如果修改后问题依旧：**
那说明问题出在**前端 (Frontend)**。前端代码可能写了类似 `if (!config.is_enabled) form.clear()` 的逻辑。因为保存 Provider 2 后，Provider 1 变成了 `Disabled`，前端可能误以为它未配置而清空了显示。这种情况下，虽然数据库里的 Key 还在，但你看不到了。