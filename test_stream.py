import os
from openai import OpenAI

# 1. 配置（和你的 .env 保持一致）
os.environ['https_proxy'] = 'http://127.0.0.1:7890' # 你的代理端口
api_key = "sk-714a19818dac43f89b638e8f8422da0e"
base_url = "https://api.deepseek.com"

print("🚀 开始测试原生 OpenAI 流式连接...")

client = OpenAI(api_key=api_key, base_url=base_url)

try:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "你好，请帮我写一段300字的科幻小说开头。"},
        ],
        stream=True # 开启流式
    )

    print("✅ 连接成功，准备接收数据...\n")
    print("-" * 20)
    
    for chunk in response:
        # DeepSeek 的思考内容通常在这里
        if hasattr(chunk.choices[0].delta, 'reasoning_content'):
            r_content = chunk.choices[0].delta.reasoning_content
            if r_content:
                print(f"[思考] {r_content}", end="", flush=True)
        
        # 正式内容在这里
        content = chunk.choices[0].delta.content
        if content:
            print(content, end="", flush=True)
            
    print("\n" + "-" * 20)
    print("\n✅ 测试结束")

except Exception as e:
    print(f"\n❌ 测试失败: {e}")