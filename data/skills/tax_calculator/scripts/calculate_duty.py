#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能脚本：关税和增值税计算器
输入：通过命令行参数接收 JSON 字符串
输出：将结果打印到 stdout（JSON 格式）
"""

import sys
import json

def main():
    # 1. 检查参数
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少参数"}, ensure_ascii=False))
        sys.exit(1)

    # 2. 解析 JSON 参数
    try:
        args = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        print(json.dumps({"error": "参数 JSON 格式无效"}, ensure_ascii=False))
        sys.exit(1)

    # 3. 提取参数
    cif_price = args.get('cif_price', 0)
    hs_code = args.get('hs_code', '')

    # 4. 业务逻辑处理
    # HS "85423100" (芯片) → 关税 0%，增值税 13%
    # 其他 → 关税 5%，增值税 13%

    if hs_code == "85423100":
        duty_rate = 0.0  # 关税 0%
    else:
        duty_rate = 0.05  # 关税 5%

    vat_rate = 0.13  # 增值税 13%

    # 计算关税和增值税
    duty = cif_price * duty_rate
    vat = (cif_price + duty) * vat_rate
    total = duty + vat

    # 5. 输出结果（JSON 格式）
    result = {
        "duty": round(duty, 2),
        "vat": round(vat, 2),
        "total": round(total, 2),
        "duty_rate": duty_rate,
        "vat_rate": vat_rate,
        "hs_code": hs_code
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
