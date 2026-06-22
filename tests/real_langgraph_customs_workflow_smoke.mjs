import assert from "node:assert/strict";
import crypto from "node:crypto";

const baseUrl = "http://127.0.0.1:8000/api/agent/v1";
const tenantId = "langgraph-e2e";
const cases = [
    "normal_release",
    "returned_then_release",
    "high_risk_inspection"
];

for (const mockCaseId of cases) {
    const requestId = `langgraph-${crypto.randomUUID()}`;
    const headers = {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
        "X-Tenant-ID": tenantId,
        "X-Service-Name": "langgraph-customs-e2e"
    };
    const createResponse = await fetch(`${baseUrl}/runs`, {
        method: "POST",
        headers,
        body: JSON.stringify({
            request_id: requestId,
            session: {
                session_id: `langgraph-${mockCaseId}-${Date.now()}`,
                user_id: "langgraph-proof-user",
                tenant_id: tenantId
            },
            message: {
                role: "user",
                content: `真实 LangGraph 海关智能体演示 ${mockCaseId}`
            },
            business_context: {
                mock_case_id: mockCaseId,
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
        assert.equal(response.status, 200);
        snapshot = await response.json();
        if (["completed", "failed", "cancelled"].includes(snapshot.status)) break;
        await new Promise(resolve => setTimeout(resolve, 250));
    }

    assert.equal(snapshot.status, "completed");
    const result = snapshot.structured_result;
    assert.equal(result.customs_stage, "CLOSED");
    assert.equal(result.mock, true);
    assert.equal(
        result.analysis_results.goods_classification.model_invoked,
        true
    );
    assert.equal(
        result.analysis_results.goods_classification.fallback_used,
        false
    );
    assert.ok(result.authority_decisions.length >= 2);
    assert.ok(
        result.authority_decisions.every(
            decision =>
                decision.model_invoked === true
                && decision.fallback_used === false
                && decision.model_version
        )
    );
    assert.ok(snapshot.outputs.length >= 4);

    const eventResponse = await fetch(
        `${baseUrl}/runs/${created.run_id}/events`,
        { headers: { ...headers, Accept: "text/event-stream" } }
    );
    const events = await eventResponse.text();
    for (const toolName of [
        "normalize_declaration_data",
        "classify_goods",
        "check_regulatory_requirements",
        "estimate_customs_tax",
        "pre_audit_declaration",
        "submit_customs_declaration",
        "process_customs_acceptance",
        "process_customs_review",
        "pay_mock_customs_tax",
        "release_mock_goods",
        "close_import_case"
    ]) {
        assert.match(events, new RegExp(`"tool":"${toolName}"`));
    }
    assert.match(events, /event: customs_process_updated/);
    assert.match(events, /event: output_created/);

    if (mockCaseId === "returned_then_release") {
        assert.equal(result.declaration_version_count, 2);
        assert.equal(result.amendment_count, 1);
    }
    if (mockCaseId === "high_risk_inspection") {
        assert.equal(result.inspection.result, "MATCHED");
        assert.match(events, /"tool":"respond_to_price_query"/);
        assert.match(events, /"tool":"schedule_mock_inspection"/);
        assert.match(events, /"tool":"submit_inspection_result"/);
    }

    console.log(JSON.stringify({
        mock_case_id: mockCaseId,
        run_id: created.run_id,
        business_case_id: result.business_case_id,
        classifier_model: (
            result.analysis_results.goods_classification.model_version
        ),
        authority_decisions: result.authority_decisions.length,
        stage: result.customs_stage
    }));
}
