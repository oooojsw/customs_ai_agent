import assert from "node:assert/strict";
import crypto from "node:crypto";

const apiBase = "http://127.0.0.1:8000/api/agent/v1";
const requestId = `pen-risk-${crypto.randomUUID()}`;
const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": requestId,
    "X-Tenant-ID": "pen-risk-proof",
    "X-Service-Name": "pen-risk-proof"
};

const declaration = {
    consignee: "演示进口企业",
    overseas_consignor: "Vietnam Pen Co., Ltd.",
    trade_mode: "0110",
    transport_mode: "海运",
    bill_of_lading_no: "TEST-005-BL",
    invoice_no: "TEST-005-INV",
    contract_no: "TEST-005-CON",
    packing_list_no: "TEST-005-PL",
    currency: "USD",
    incoterm: "CIF",
    freight: 0,
    insurance: 0,
    goods: [{
        item_no: 1,
        name: "塑料圆珠笔",
        hs_code: "96081000",
        quantity: 5000,
        quantity_unit: "支",
        unit_price: 100,
        total_price: 500000,
        currency: "USD",
        gross_weight: 600,
        net_weight: 500,
        origin_country: "越南",
        brand: "无名",
        model: "普通塑料圆珠笔",
        usage: "书写",
        material: "塑料"
    }]
};

const response = await fetch(`${apiBase}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
        request_id: requestId,
        session: {
            session_id: requestId,
            user_id: "pen-risk-user",
            tenant_id: "pen-risk-proof"
        },
        message: { role: "user", content: "直接模拟申报这票圆珠笔" },
        business_context: {
            declaration,
            documents: [
                { document_id: "TEST-005-CON", document_type: "contract" },
                { document_id: "TEST-005-INV", document_type: "invoice" },
                { document_id: "TEST-005-PL", document_type: "packing_list" },
                { document_id: "TEST-005-BL", document_type: "bill_of_lading" }
            ],
            step_delay_ms: 0
        },
        options: {
            intent: "mock_import_declaration",
            response_mode: "poll",
            output_file_policy: "none",
            timeout_seconds: 300
        }
    })
});
assert.equal(response.status, 202);
const created = await response.json();

let run;
for (let attempt = 0; attempt < 600; attempt += 1) {
    const poll = await fetch(`${apiBase}/runs/${created.run_id}`, { headers });
    run = await poll.json();
    if (["completed", "failed", "cancelled"].includes(run.status)) break;
    await new Promise(resolve => setTimeout(resolve, 250));
}

assert.equal(run.status, "completed");
const result = run.structured_result;
const findings = result.analysis_results.pre_audit.review_findings;
const codes = new Set(findings.map(finding => finding.code));
assert.ok(codes.has("PRICE_STATIONERY_UNIT_VALUE_OUTLIER"));
assert.ok(codes.has("PRICE_AML_TRADE_OVERSTATEMENT_RED_FLAG"));
assert.equal(result.analysis_results.pre_audit.risk_detected, true);
assert.equal(result.analysis_results.pre_audit.risk_level, "high");
assert.ok(
    result.authority_decisions.some(
        decision => decision.receipt_type === "CUSTOMS_PRICE_QUERY_NOTICE"
    )
);

const snapshotResponse = await fetch(
    `http://127.0.0.1:8000/internal/customs-simulator/v1/cases/${result.business_case_id}`
);
assert.equal(snapshotResponse.status, 200);
const snapshot = await snapshotResponse.json();
const persistedDeclaration = snapshot.declaration_versions.at(-1).declaration;
assert.equal(snapshot.case_source, "custom_declaration");
assert.equal(persistedDeclaration.goods[0].name, "塑料圆珠笔");
assert.equal(persistedDeclaration.goods[0].hs_code, "96081000");
assert.equal(persistedDeclaration.goods[0].total_price, 500000);

console.log(JSON.stringify({
    run_id: created.run_id,
    business_case_id: result.business_case_id,
    case_source: snapshot.case_source,
    goods: persistedDeclaration.goods[0].name,
    risk_codes: [...codes],
    final_stage: result.customs_stage
}));
