import assert from "node:assert/strict";
import crypto from "node:crypto";

const baseUrl = "http://127.0.0.1:8000/api/agent/v1";
const uniqueId = crypto.randomUUID();
const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": `general-pen-${uniqueId}`,
    "X-Tenant-ID": "general-pen-proof",
    "X-Service-Name": "general-pen-proof"
};
const message = `
使用下面的数据创建一票自定义 Mock 进口申报案件。缺少真实单证时，请生成与本票数据绑定的 Mock 单证。
只执行到申报前预审并报告全部风险，不要向海关提交，不要使用任何固定演示案例。
报关单号：TEST-005
货物名称：塑料圆珠笔
HS编码：96081000
数量：5000 支
单价：100.00 USD
总价：500000.00 USD
原产国：越南
申报要素：品牌无名，材质塑料，用途书写，型号普通塑料圆珠笔。
`.trim();

const response = await fetch(`${baseUrl}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
        request_id: `general-pen-${uniqueId}`,
        session: {
            session_id: `general-pen-${uniqueId}`,
            user_id: "general-pen-user",
            tenant_id: "general-pen-proof"
        },
        message: { role: "user", content: message },
        options: {
            intent: "auto",
            response_mode: "poll",
            include_tool_trace: true,
            output_file_policy: "none",
            timeout_seconds: 300
        }
    })
});
assert.equal(response.status, 202);
const created = await response.json();

let run;
for (let attempt = 0; attempt < 600; attempt += 1) {
    const poll = await fetch(`${baseUrl}/runs/${created.run_id}`, { headers });
    run = await poll.json();
    if (["completed", "failed", "cancelled"].includes(run.status)) break;
    await new Promise(resolve => setTimeout(resolve, 500));
}

assert.equal(run.status, "completed");
const verified = run.structured_result.verified_customs_case;
assert.ok(verified, "通用智能体未返回持久化案件核验结果");
assert.equal(verified.case_source, "custom_declaration");
assert.equal(verified.goods[0].name, "塑料圆珠笔");
assert.equal(verified.goods[0].hs_code, "96081000");
assert.equal(verified.goods[0].quantity, 5000);
assert.equal(verified.goods[0].unit_price, 100);
assert.equal(verified.goods[0].total_price, 500000);
assert.match(run.final_answer, /系统核验/);
assert.doesNotMatch(run.final_answer, /集成电路|85423100/);

console.log(JSON.stringify({
    run_id: created.run_id,
    business_case_id: verified.business_case_id,
    case_source: verified.case_source,
    stage: verified.stage,
    goods: verified.goods[0],
    answer_tail: run.final_answer.slice(-300)
}));
