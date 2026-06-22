import assert from "node:assert/strict";
import crypto from "node:crypto";

const baseUrl = "http://127.0.0.1:8000/api/agent/v1";
const requestId = `custom-goods-${crypto.randomUUID()}`;
const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": requestId,
    "X-Tenant-ID": "custom-goods-proof",
    "X-Service-Name": "custom-goods-proof"
};
const declaration = {
    consignee: "杭州纺织品进口有限公司",
    overseas_consignor: "Vietnam Fabric Co., Ltd.",
    trade_mode: "0110",
    transport_mode: "海运",
    bill_of_lading_no: "TEXTILE-BL-2026",
    invoice_no: "TEXTILE-INV-2026",
    contract_no: "TEXTILE-CON-2026",
    packing_list_no: "TEXTILE-PL-2026",
    currency: "USD",
    incoterm: "CIF",
    freight: 600,
    insurance: 80,
    goods: [{
        item_no: 1,
        name: "涤纶针织染色布",
        hs_code: "60063200",
        quantity: 10000,
        quantity_unit: "米",
        unit_price: 2.5,
        total_price: 25000,
        currency: "USD",
        gross_weight: 2200,
        net_weight: 2100,
        origin_country: "越南",
        brand: "V-FABRIC",
        model: "PF-150",
        usage: "服装面料",
        material: "100% 聚酯纤维"
    }]
};
const documents = [
    { document_id: "TEXTILE-CON", document_type: "contract" },
    { document_id: "TEXTILE-INV", document_type: "invoice" },
    { document_id: "TEXTILE-PL", document_type: "packing_list" },
    { document_id: "TEXTILE-BL", document_type: "bill_of_lading" }
];

const createResponse = await fetch(`${baseUrl}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
        request_id: requestId,
        session: {
            session_id: `custom-goods-${Date.now()}`,
            user_id: "custom-goods-user",
            tenant_id: "custom-goods-proof"
        },
        message: {
            role: "user",
            content: "使用结构化纺织品资料演示完整进口报关"
        },
        business_context: {
            declaration,
            documents,
            workflow_config: {
                exchange_rate: 7.2,
                duty_rate: 0.08,
                vat_rate: 0.13
            },
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
assert.equal(createResponse.status, 202);
const created = await createResponse.json();

let snapshot;
for (let attempt = 0; attempt < 600; attempt += 1) {
    const response = await fetch(`${baseUrl}/runs/${created.run_id}`, {
        headers
    });
    snapshot = await response.json();
    if (["completed", "failed", "cancelled"].includes(snapshot.status)) break;
    await new Promise(resolve => setTimeout(resolve, 250));
}

assert.equal(snapshot.status, "completed");
const result = snapshot.structured_result;
assert.equal(result.customs_stage, "CLOSED");
assert.equal(
    result.analysis_results.goods_classification.model_invoked,
    true
);
assert.equal(
    result.analysis_results.goods_classification.fallback_used,
    false
);
assert.equal(
    result.analysis_results.goods_classification.candidates[0].declared_hs_code,
    "60063200"
);
assert.ok(
    result.authority_decisions.every(
        decision =>
            decision.model_invoked === true
            && decision.fallback_used === false
    )
);

console.log(JSON.stringify({
    run_id: created.run_id,
    business_case_id: result.business_case_id,
    declared_hs_code: "60063200",
    candidate_hs_codes: (
        result.analysis_results.goods_classification
            .candidates[0].candidate_hs_codes
    ),
    authority_decisions: result.authority_decisions.length,
    stage: result.customs_stage
}));
