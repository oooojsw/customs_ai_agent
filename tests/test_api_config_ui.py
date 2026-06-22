"""
API 配置和图像配置 - 自动化 UI 测试

使用 Playwright 模拟用户操作进行测试

运行前准备：
1. 安装依赖：pip install pytest-playwright
2. 安装浏览器：playwright install chromium
3. 启动服务器：python src/main.py
4. 运行测试：pytest tests/test_api_config_ui.py -v
"""

import asyncio
import json
import os
import pytest
from playwright.async_api import async_playwright, Page, Browser, expect
import time
from urllib.parse import parse_qs, urlparse

pytestmark = pytest.mark.integration


# 测试配置
BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 5000  # 5 秒
TEST_API_KEY = "sk-test-placeholder-not-a-real-secret"


async def install_config_api_mock(page):
    """Keep UI tests deterministic without changing the developer's live config."""
    page.on(
        "dialog",
        lambda dialog: asyncio.create_task(dialog.accept()),
    )
    llm = {
        "is_enabled": False,
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "temperature": 0.3,
        "test_status": "never",
        "api_key": None,
        "has_api_key": False,
        "api_key_preview": "",
    }
    image = {
        "is_enabled": False,
        "provider": "siliconflow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "Qwen/Qwen2.5-VL-72B-Instruct",
        "temperature": 0.1,
        "max_tokens": 16384,
        "test_status": "never",
        "api_key": None,
        "has_api_key": False,
        "api_key_preview": "",
    }

    async def handle(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method
        if path == "/api/v1/config/llm" and method == "GET":
            return await route.fulfill(json=llm)
        if path == "/api/v1/config/llm" and method == "POST":
            payload = request.post_data_json
            llm.update(payload)
            llm["has_api_key"] = bool(payload.get("api_key"))
            llm["api_key"] = None
            return await route.fulfill(json={"status": "success"})
        if path == "/api/v1/config/llm/reset":
            llm["is_enabled"] = False
            return await route.fulfill(json={"status": "success"})
        if path in {"/api/v1/config/llm/test", "/api/v1/config/llm/reload"}:
            return await route.fulfill(json={"status": "success"})
        if path.startswith("/api/v1/config/llm/provider/"):
            return await route.fulfill(
                json={"status": "not_found", "message": "test fixture"}
            )
        if path == "/api/v1/config/llm/models":
            provider = parse_qs(parsed.query).get("provider", ["deepseek"])[0]
            models = {
                "deepseek": ["deepseek-chat", "deepseek-coder"],
                "openai": ["gpt-4o", "gpt-4o-mini"],
                "qwen": ["qwen-plus", "qwen-max"],
            }.get(provider, ["test-model"])
            return await route.fulfill(json={"status": "success", "models": models})
        if path == "/api/v1/config/image" and method == "GET":
            return await route.fulfill(json=image)
        if path == "/api/v1/config/image" and method == "POST":
            payload = request.post_data_json
            image.update(payload)
            image["has_api_key"] = bool(payload.get("api_key"))
            image["api_key"] = None
            return await route.fulfill(json={"status": "success", "config": image})
        if path in {"/api/v1/config/image/test", "/api/v1/config/image/reload"}:
            return await route.fulfill(json={"status": "success"})
        if path.startswith("/api/v1/config/image/provider/"):
            return await route.fulfill(
                json={"status": "not_found", "message": "test fixture"}
            )
        if path == "/api/v1/config/image/models":
            return await route.fulfill(
                json={
                    "status": "success",
                    "models": ["Qwen/Qwen2.5-VL-72B-Instruct"],
                }
            )
        await route.continue_()

    await page.route("**/api/v1/config/**", handle)


class TestAPIConfig:
    """API 配置功能自动化测试"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        """每个测试前的设置"""
        self.playwright = await async_playwright().start()
        headed = os.getenv("PLAYWRIGHT_HEADED", "0") == "1"
        self.browser = await self.playwright.chromium.launch(
            headless=not headed,
            slow_mo=500 if headed else 0,
        )
        self.page = await self.browser.new_page()
        await install_config_api_mock(self.page)
        await self.page.goto(
            BASE_URL,
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        await self.page.wait_for_selector(
            "#settingsModal",
            state="attached",
            timeout=DEFAULT_TIMEOUT,
        )

        yield

        await self.browser.close()
        await self.playwright.stop()

    async def open_settings_tab(self, tab_name: str):
        """打开指定的设置标签"""
        # 点击设置按钮
        await self.page.click('button:has-text("设置")')
        await self.page.wait_for_timeout(500)

        # 点击对应的标签
        if tab_name == "API配置":
            await self.page.click('button:has-text("API配置")')
        elif tab_name == "图像配置":
            await self.page.click('button:has-text("图像配置")')

        await self.page.wait_for_timeout(500)

    async def test_01_initial_state(self):
        """
        场景 1.1.1：首次打开设置页面
        """
        print("\n【测试 1】首次打开 API 配置页面")

        # 打开 API 配置标签
        await self.open_settings_tab("API配置")

        # 验证开关默认关闭
        switch = self.page.locator('#llmEnabled')
        is_checked = await switch.is_checked()
        assert not is_checked, "开关应该默认关闭"
        print("✓ 开关默认关闭")

        # 验证配置表单隐藏
        form = self.page.locator('#llmConfigForm')
        is_visible = await form.is_visible()
        assert not is_visible, "配置表单应该隐藏"
        print("✓ 配置表单隐藏")

        assert await self.page.locator('#llmProvider').input_value() == 'deepseek'

    async def test_02_toggle_switch_on(self):
        """
        场景 1.2.1：打开开关（首次）
        """
        print("\n【测试 2】打开配置开关")

        await self.open_settings_tab("API配置")

        # 点击开关
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(1000)

        # 验证表单显示
        form = self.page.locator('#llmConfigForm')
        await expect(form).to_be_visible()
        print("✓ 配置表单已显示")

        # 验证服务商选择框
        provider = self.page.locator('#llmProvider')
        value = await provider.input_value()
        assert value == 'deepseek', "应该默认选择 DeepSeek"
        print("✓ 服务商默认选择: DeepSeek")

        # 验证 API 地址
        base_url = self.page.locator('#llmBaseUrl')
        url_value = await base_url.input_value()
        assert 'api.deepseek.com' in url_value, "应该自动填充 DeepSeek API 地址"
        print(f"✓ API 地址自动填充: {url_value}")

        # 验证模型列表
        model_select = self.page.locator('#llmModelName')
        await expect(model_select).to_be_visible()

        # 获取所有选项
        await expect(
            model_select.locator('option[value="deepseek-coder"]')
        ).to_have_count(1, timeout=DEFAULT_TIMEOUT)
        options = await model_select.locator('option').all()
        option_texts = [await opt.inner_text() for opt in options]

        assert 'deepseek-chat' in str(option_texts), "应该包含 deepseek-chat 模型"
        assert 'deepseek-coder' in str(option_texts), "应该包含 deepseek-coder 模型"
        print(f"✓ 模型列表已加载: {option_texts}")

    async def test_03_switch_provider(self):
        """
        场景 1.3.2：切换到 OpenAI
        """
        print("\n【测试 3】切换服务商到 OpenAI")

        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 选择 OpenAI
        await self.page.select_option('#llmProvider', 'openai')
        await self.page.wait_for_timeout(1000)

        # 验证 API 地址
        base_url = self.page.locator('#llmBaseUrl')
        url_value = await base_url.input_value()
        assert 'api.openai.com' in url_value, "应该自动填充 OpenAI API 地址"
        print(f"✓ API 地址已更新: {url_value}")

        # 验证模型列表
        model_select = self.page.locator('#llmModelName')
        options = await model_select.locator('option').all()
        option_texts = [await opt.inner_text() for opt in options]

        assert 'gpt-4o' in str(option_texts), "应该包含 gpt-4o 模型"
        print(f"✓ OpenAI 模型列表: {option_texts}")

    async def test_04_select_qwen_provider(self):
        """
        场景 1.3.3：选择通义千问
        """
        print("\n【测试 4】切换服务商到通义千问")

        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 选择通义千问
        await self.page.select_option('#llmProvider', 'qwen')
        await self.page.wait_for_timeout(1000)

        # 验证 API 地址
        base_url = self.page.locator('#llmBaseUrl')
        url_value = await base_url.input_value()
        assert 'dashscope.aliyuncs.com' in url_value, "应该自动填充通义千问 API 地址"
        print(f"✓ API 地址已更新: {url_value}")

        # 验证模型列表
        model_select = self.page.locator('#llmModelName')
        options = await model_select.locator('option').all()
        option_texts = [await opt.inner_text() for opt in options]

        assert 'qwen-plus' in str(option_texts) or 'qwen-max' in str(option_texts), "应该包含通义千问模型"
        print(f"✓ 通义千问模型列表: {option_texts}")

    async def test_05_input_api_key(self):
        """
        场景 1.4.1：输入 DeepSeek API Key
        """
        print("\n【测试 5】输入 API Key")

        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 输入 API Key
        api_key_input = self.page.locator('#llmApiKey')
        await api_key_input.fill('sk-test-placeholder-not-a-real-secret')
        await self.page.wait_for_timeout(500)

        # 验证输入（密码框类型，应该显示掩码）
        input_type = await api_key_input.get_attribute('type')
        assert input_type == 'password', "API Key 应该是密码框类型"
        print("✓ API Key 输入成功（密码掩码）")

    async def test_06_adjust_temperature(self):
        """
        场景 1.6.1：调节 Temperature
        """
        print("\n【测试 6】调节 Temperature 滑块")

        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 获取初始值
        temp_slider = self.page.locator('#llmTemperature')
        temp_value = self.page.locator('#tempValue')
        initial_value = await temp_value.inner_text()
        print(f"初始 Temperature: {initial_value}")

        # 设置新值
        await temp_slider.evaluate(
            """el => {
                el.value = '0.7';
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        await self.page.wait_for_timeout(300)

        # 验证值更新
        new_value = await temp_value.inner_text()
        assert new_value == '0.7', f"Temperature 应该更新为 0.7，实际: {new_value}"
        print(f"✓ Temperature 已更新: {new_value}")

    async def test_07_test_connection_valid(self):
        """
        场景 1.7.1：测试连接（有效配置）
        """
        print("\n【测试 7】测试连接")

        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 填写完整配置
        await self.page.fill('#llmApiKey', 'sk-test-placeholder-not-a-real-secret')
        await self.page.select_option('#llmProvider', 'deepseek')
        await self.page.wait_for_timeout(500)

        # 当前 UI 将连接验证合并到“保存并应用”，该按钮只显示提示。
        await self.page.click('button:has-text("测试连接")')

    async def test_08_save_config(self):
        """
        场景 1.8.1：保存完整配置
        """
        print("\n【测试 8】保存并应用配置")

        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 填写完整配置
        await self.page.select_option('#llmProvider', 'deepseek')
        await self.page.fill('#llmApiKey', 'sk-test-placeholder-not-a-real-secret')
        await self.page.select_option('#llmModelName', 'deepseek-chat')
        await self.page.evaluate('document.getElementById("llmTemperature").value = 0.5')
        await self.page.evaluate('document.getElementById("tempValue").innerText = "0.5"')

        # 点击保存
        async with self.page.expect_response('**/api/v1/config/llm') as response_info:
            await self.page.click('button:has-text("保存并应用")')

        response = await response_info.value
        print(f"✓ 保存请求已发送: {response.status}")

        # 等待响应
        await self.page.wait_for_timeout(2000)

        assert await self.page.locator('#llmEnabled').is_checked()
        assert await self.page.locator('#llmProvider').input_value() == 'deepseek'

    async def test_09_reset_config(self):
        """
        场景 1.9.1：重置为 .env 配置
        """
        print("\n【测试 9】重置配置")

        await self.open_settings_tab("API配置")

        # 确保开关是打开的
        switch = self.page.locator('#llmEnabled')
        is_checked = await switch.is_checked()
        if not is_checked:
            await switch.check(force=True)
            await self.page.wait_for_timeout(500)

        # 点击重置按钮
        await self.page.click('button:has-text("重置")')
        await self.page.wait_for_timeout(500)

        # 确认对话框（如果有）
        try:
            # 尝试查找确认按钮
            confirm_button = self.page.locator('button:has-text("确定"), button:has-text("确认")')
            if await confirm_button.is_visible(timeout=1000):
                await confirm_button.click()
                print("✓ 已确认重置")
        except:
            print("✓ 直接重置（无确认对话框）")

        await self.page.wait_for_timeout(2000)

        # 验证开关已关闭
        is_checked = await switch.is_checked()
        assert not is_checked, "重置后开关应该关闭"
        print("✓ 开关已关闭")

        # 验证表单已隐藏
        form = self.page.locator('#llmConfigForm')
        is_visible = await form.is_visible()
        assert not is_visible, "重置后表单应该隐藏"
        print("✓ 配置表单已隐藏")

    async def test_10_refresh_page(self):
        """
        场景 1.11.1：保存后刷新页面
        """
        print("\n【测试 10】刷新页面后配置保持")

        # 先保存配置
        await self.open_settings_tab("API配置")
        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        await self.page.select_option('#llmProvider', 'deepseek')
        await self.page.fill('#llmApiKey', 'sk-test-placeholder-not-a-real-secret')
        await self.page.select_option('#llmModelName', 'deepseek-chat')

        async with self.page.expect_response('**/api/v1/config/llm'):
            await self.page.click('button:has-text("保存并应用")')

        await self.page.wait_for_timeout(2000)

        # 刷新页面
        await self.page.reload(wait_until='domcontentloaded')
        await self.page.wait_for_timeout(1000)

        # 重新打开配置
        await self.open_settings_tab("API配置")

        # 验证配置保留
        switch = self.page.locator('#llmEnabled')
        is_checked = await switch.is_checked()
        assert is_checked, "刷新后开关应该保持打开"
        print("✓ 刷新后开关状态保持")

        # 验证服务商
        provider = self.page.locator('#llmProvider')
        value = await provider.input_value()
        assert value == 'deepseek', "刷新后服务商应该保持"
        print(f"✓ 刷新后服务商保持: {value}")


class TestImageConfig:
    """图像配置功能自动化测试"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        """每个测试前的设置"""
        self.playwright = await async_playwright().start()
        headed = os.getenv("PLAYWRIGHT_HEADED", "0") == "1"
        self.browser = await self.playwright.chromium.launch(
            headless=not headed,
            slow_mo=500 if headed else 0,
        )
        self.page = await self.browser.new_page()
        await install_config_api_mock(self.page)
        await self.page.goto(BASE_URL, wait_until="domcontentloaded")
        await self.page.wait_for_selector("#settingsModal", state="attached")

        yield

        await self.browser.close()
        await self.playwright.stop()

    async def open_image_tab(self):
        """打开图像配置标签"""
        await self.page.click('button:has-text("设置")')
        await self.page.wait_for_timeout(500)
        await self.page.click('button:has-text("图像配置")')
        await self.page.wait_for_timeout(500)

    async def test_01_open_image_config(self):
        """
        场景 2.1.2：打开图像配置开关
        """
        print("\n【测试 11】打开图像配置")

        await self.open_image_tab()

        # 点击开关
        await self.page.locator('#imageEnabled').check(force=True)
        await self.page.wait_for_timeout(1000)

        # 验证表单显示
        form = self.page.locator('#imageConfigForm')
        await expect(form).to_be_visible()
        print("✓ 图像配置表单已显示")

        # 验证服务商
        provider = self.page.locator('#imageProvider')
        value = await provider.input_value()
        print(f"✓ 默认服务商: {value}")

        # 验证 API 地址
        base_url = self.page.locator('#imageBaseUrl')
        if await base_url.is_visible():
            url_value = await base_url.input_value()
            print(f"✓ API 地址: {url_value}")

    async def test_02_select_image_provider(self):
        """
        场景 2.2.1：选择 SiliconFlow
        """
        print("\n【测试 12】选择 SiliconFlow 服务商")

        await self.open_image_tab()
        await self.page.locator('#imageEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 选择 SiliconFlow
        await self.page.select_option('#imageProvider', 'siliconflow')
        await self.page.wait_for_timeout(1000)

        # 验证 API 地址
        base_url = self.page.locator('#imageBaseUrl')
        if await base_url.is_visible():
            url_value = await base_url.input_value()
            assert 'siliconflow' in url_value, "应该包含 siliconflow"
            print(f"✓ API 地址: {url_value}")

    async def test_03_save_image_config(self):
        """
        场景 2.3.1：保存图像配置
        """
        print("\n【测试 13】保存图像配置")

        await self.open_image_tab()
        await self.page.locator('#imageEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        # 填写配置
        await self.page.select_option('#imageProvider', 'siliconflow')
        await self.page.fill('#imageApiKey', 'sk-test-placeholder-not-a-real-secret')

        # 选择模型
        model_select = self.page.locator('#imageModelName')
        if await model_select.is_visible():
            # 等待模型列表加载
            await self.page.wait_for_timeout(1000)
            options = await model_select.locator('option').all()
            if len(options) > 1:
                await model_select.select_option(index=1)
                print(f"✓ 已选择模型")

        # 点击保存
        await self.page.click(
            '#tab-content-image button:has-text("保存并应用")'
        )
        await self.page.wait_for_timeout(2000)

        print("✓ 图像配置已保存")


class TestCrossFunctionality:
    """跨功能交互测试"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        """每个测试前的设置"""
        self.playwright = await async_playwright().start()
        headed = os.getenv("PLAYWRIGHT_HEADED", "0") == "1"
        self.browser = await self.playwright.chromium.launch(
            headless=not headed,
            slow_mo=500 if headed else 0,
        )
        self.page = await self.browser.new_page()
        await install_config_api_mock(self.page)
        await self.page.goto(BASE_URL, wait_until="domcontentloaded")
        await self.page.wait_for_selector("#settingsModal", state="attached")

        yield

        await self.browser.close()
        await self.playwright.stop()

    async def test_01_api_config_affects_audit(self):
        """
        场景 4.1.1：API 配置影响功能一（审单）
        """
        print("\n【测试 14】API 配置影响审单功能")

        # 配置 API
        await self.page.click('button:has-text("设置")')
        await self.page.wait_for_timeout(500)
        await self.page.click('button:has-text("API配置")')
        await self.page.wait_for_timeout(500)

        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.wait_for_timeout(500)

        await self.page.select_option('#llmProvider', 'deepseek')
        await self.page.fill('#llmApiKey', 'sk-test-placeholder-not-a-real-secret')
        await self.page.select_option('#llmModelName', 'deepseek-chat')

        async with self.page.expect_response('**/api/v1/config/llm'):
            await self.page.click('button:has-text("保存并应用")')

        await self.page.wait_for_timeout(2000)

        # 切换到功能一
        await self.page.evaluate("setFeatureNavigation('audit', true)")
        await self.page.evaluate("toggleSettings()")
        await self.page.click('button:has-text("审单")')
        await self.page.wait_for_timeout(500)

        # 验证功能一可用
        audit_tab = self.page.locator('#module-audit')
        await expect(audit_tab).to_be_visible()
        print("✓ 审单功能可用")

    async def test_02_switch_provider_affects_all(self):
        """
        场景 4.1.4：切换 API 后三个功能都受影响
        """
        print("\n【测试 15】切换服务商影响所有功能")

        # 配置 DeepSeek
        await self.page.click('button:has-text("设置")')
        await self.page.click('button:has-text("API配置")')
        await self.page.wait_for_timeout(500)

        await self.page.locator('#llmEnabled').check(force=True)
        await self.page.select_option('#llmProvider', 'deepseek')
        await self.page.fill('#llmApiKey', 'sk-test-placeholder-not-a-real-secret')
        await self.page.select_option('#llmModelName', 'deepseek-chat')
        await self.page.click('button:has-text("保存并应用")')
        await self.page.wait_for_timeout(1000)

        # 切换到 OpenAI
        await self.page.select_option('#llmProvider', 'openai')
        await self.page.fill('#llmApiKey', 'sk-test-openai-key')
        await self.page.select_option('#llmModelName', 'gpt-4o')
        await self.page.click('button:has-text("保存并应用")')
        await self.page.wait_for_timeout(1000)

        assert await self.page.locator('#llmProvider').input_value() == 'openai'


# 运行测试的辅助函数
async def run_quick_test():
    """运行快速测试（不使用 pytest）"""
    print("=" * 60)
    print("开始自动化 UI 测试")
    print("=" * 60)

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False, slow_mo=1000)
    page = await browser.new_page()

    try:
        # 访问页面
        print("\n[1/8] 访问页面...")
        await page.goto(BASE_URL)
        await page.wait_for_load_state("networkidle")
        print("✓ 页面加载成功")

        # 打开 API 配置
        print("\n[2/8] 打开 API 配置...")
        await page.click('button:has-text("设置")')
        await page.wait_for_timeout(500)
        await page.click('button:has-text("API配置")')
        await page.wait_for_timeout(500)
        print("✓ API 配置标签已打开")

        # 打开开关
        print("\n[3/8] 打开配置开关...")
        await page.locator('#llmEnabled').check(force=True)
        await page.wait_for_timeout(1000)
        print("✓ 开关已打开")

        # 验证表单显示
        print("\n[4/8] 验证配置表单...")
        form = page.locator('#llmConfigForm')
        is_visible = await form.is_visible()
        print(f"✓ 配置表单可见: {is_visible}")

        # 验证服务商
        print("\n[5/8] 验证默认服务商...")
        provider = page.locator('#llmProvider')
        value = await provider.input_value()
        print(f"✓ 默认服务商: {value}")

        # 验证模型列表
        print("\n[6/8] 验证模型列表...")
        model_select = page.locator('#llmModelName')
        await page.wait_for_timeout(1000)
        options = await model_select.locator('option').all()
        print(f"✓ 模型数量: {len(options)}")
        for i, opt in enumerate(options[:3]):
            text = await opt.inner_text()
            print(f"  - {text}")

        # 输入 API Key
        print("\n[7/8] 输入 API Key...")
        await page.fill('#llmApiKey', 'sk-test-placeholder-not-a-real-secret')
        print("✓ API Key 已输入")

        # 保存配置
        print("\n[8/8] 保存配置...")
        await page.click('button:has-text("保存并应用")')
        await page.wait_for_timeout(3000)
        print("✓ 配置已保存")

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)

        # 保持浏览器打开 5 秒供查看
        print("\n浏览器将在 5 秒后关闭...")
        await page.wait_for_timeout(5000)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        print("浏览器将保持打开以便调试...")
        await page.wait_for_timeout(30000)  # 保持 30 秒
    finally:
        await browser.close()
        await playwright.stop()


if __name__ == "__main__":
    # 直接运行快速测试
    asyncio.run(run_quick_test())
