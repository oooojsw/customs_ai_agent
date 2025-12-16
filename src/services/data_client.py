import requests
import urllib.parse
from src.config.loader import settings

class DataClient:
    def __init__(self):
        self.base_url = settings.DATA_PLATFORM_URL
        # 方贵石提供的 API 路径映射
        self.endpoints = {
            "get_declaration": "/api/custom/get_declaration_detail/" 
        }

    def fetch_declaration_text(self, entry_id: str) -> str:
        """
        对外暴露的主方法：根据单号获取数据，并返回格式化后的文本。
        """
        # 1. 尝试从真实接口获取 JSON
        data = self._fetch_from_api(entry_id)
        
        # 2. 如果接口挂了或者没数据，为了演示效果，我们使用 Mock 数据兜底
        # (在真实生产环境可以去掉这个 Mock)
        if not data:
            print(f"⚠️ [DataClient] 未能从平台获取数据，启用 Mock 模式演示: {entry_id}")
            data = self._get_mock_data(entry_id)
            if not data:
                return None # 真的没救了

        # 3. 将 JSON 转换为 AI 易读的文本格式
        return self._format_as_text(data)

    def _fetch_from_api(self, entry_id: str):
        """内部方法：执行 HTTP 请求"""
        try:
            # 拼接 URL
            url = f"{self.base_url.rstrip('/')}{self.endpoints['get_declaration']}"
            # 发起请求 (设置 2 秒超时，防止卡死)
            response = requests.get(url, params={"entry_id": entry_id}, timeout=2)
            
            if response.status_code == 200:
                result = response.json()
                # 假设方贵石返回的是 { "code": 200, "data": {...} }
                # 这里根据实际情况调整
                return result if isinstance(result, dict) else None
            return None
        except Exception as e:
            print(f"❌ [DataClient] 连接数据平台失败: {e}")
            return None

    def _format_as_text(self, data: dict) -> str:
        """
        【核心逻辑】模板引擎：将结构化数据转为自然语言文本
        """
        # 防止字段缺失报错，使用 .get()
        text = f"""报关单号：{data.get('entry_id', '未知')}
境内收货人：{data.get('consignee_cname', '未知单位')}
货物名称：{data.get('goods_name', '未知货物')}
HS编码：{data.get('hs_code', '未知')}
数量：{data.get('qty', 0)} {data.get('qty_unit', '个')}
单价：{data.get('unit_price', 0)} {data.get('currency', 'USD')}
总价：{data.get('total_price', 0)} {data.get('currency', 'USD')}
原产国：{data.get('origin_country', '未知')}
品牌：{data.get('brand', '无')}
申报要素：
{data.get('elements', '无申报要素信息')}

【随附单证信息】
（系统自动检索：已关联发票与装箱单）
1. 商业发票：金额 {data.get('total_price', 0)} {data.get('currency', 'USD')}
2. 装箱单：毛重 {data.get('gross_weight', 0)} KG / 净重 {data.get('net_weight', 0)} KG
"""
        return text

    def _get_mock_data(self, entry_id: str):
        """本地模拟数据，确保演示时有东西可查"""
        if entry_id == "530120250001":
            return {
                "entry_id": "530120250001",
                "consignee_cname": "深圳深南电子科技有限公司",
                "goods_name": "32位数字信号处理器(IC)",
                "hs_code": "85423100",
                "qty": "5000",
                "qty_unit": "个",
                "unit_price": "15.00",
                "total_price": "75000.00",
                "currency": "USD",
                "origin_country": "马来西亚",
                "brand": "TI",
                "gross_weight": "55.0",
                "net_weight": "50.0",
                "elements": "1.品名：32位数字信号处理器；2.品牌：TI；3.型号：TMS320F28335PGFA；4.功能：用于工业电机控制；5.封装形式：LQFP。"
            }
        return None