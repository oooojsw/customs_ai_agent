这是一个典型的 **"状态互斥失效" (Mutual Exclusion Failure)** 导致的 Bug。

通过分析你提供的代码（特别是 `src/database/crud.py`），我发现了问题的根源：当你保存一个 **已存在的** 供应商配置（Provider 2）时，后端**忘记禁用**之前激活的供应商（Provider 1）。这导致数据库中同时出现了两个 `is_enabled=True` 的记录。

### 1. 根本原因分析

在 `src/database/crud.py` 文件的 `save_config` 函数中，存在一个逻辑漏洞：

* **创建新配置时（Else 分支）**：代码正确调用了 `await self.disable_all_configs()`，确保新配置激活时，其他的都被禁用。
* **更新现有配置时（If existing 分支）**：代码直接设置了 `existing.is_enabled = True`，但**没有**先禁用其他配置。

**导致的结果：**

1. 你原本激活了 **Text Provider 1** (Enabled=True)。
2. 你切换到 **Text Provider 2** 并保存。如果 Provider 2 在数据库中已存在（例如之前点过或有默认值），代码走入 `if existing` 分支。
3. Provider 2 被更新为 `Enabled=True`。
4. **关键点：** Provider 1 仍然保持 `Enabled=True`。
5. 数据库现在有两个“激活”的供应商。
6. 当你切换回 Provider 1 时，系统尝试获取“当前激活的配置”（通常按更新时间倒序排列）。因为 Provider 2 刚刚被保存（更新时间最新），系统错误地将 Provider 2 当作当前配置返回，或者前端发现状态冲突（选的是1，激活的是2）导致数据显示异常（如清空显示）。

### 2. 修复方案

你需要修改 `src/database/crud.py` 文件中的 `save_config` 方法。

**文件路径：** `src/database/crud.py`
**定位代码：** 大约第 275 行左右，`save_config` 方法内部。

**修改前：**

```python
        if existing:
            # 增量更新：只有新值非空时才更新
            # ... (省略中间代码) ...
            
            # 使用前端传入的 is_enabled 值
            existing.is_enabled = config_data.get('is_enabled', True)
            
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

```

**修改后（添加一行代码）：**

```python
        if existing:
            # 增量更新：只有新值非空时才更新
            # ... (省略中间代码) ...

            # === 修复开始: 如果要启用当前配置，先禁用其他所有配置 ===
            if config_data.get('is_enabled', True):
                await self.disable_all_configs()
            # === 修复结束 ===

            # 使用前端传入的 is_enabled 值
            existing.is_enabled = config_data.get('is_enabled', True)
            
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

```

### 3. 为什么这样能解决？

加上 `await self.disable_all_configs()` 后，流程变成：

1. 保存 Provider 2。
2. 系统先将数据库中**所有**供应商（包括 Provider 1）设为 `Enabled=False`。
3. 系统将 Provider 2 设为 `Enabled=True`。
4. **结果：** 数据库中只有 Provider 2 是激活的，状态恢复唯一性。
5. 切换回 Provider 1 时，前端逻辑不再受“双重激活”的干扰，能正确加载 Provider 1 之前保存的 Key。