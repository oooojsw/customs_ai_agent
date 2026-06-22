import assert from "node:assert/strict";
import crypto from "node:crypto";

const baseUrl = "http://127.0.0.1:8000/api/agent/v1";
const tenantId = "smoke-tenant";

for (const mockCaseId of [
    "normal_release",
    "returned_then_release",
    "high_risk_inspection"
]) {
    const requestId = `mock-workflow-${crypto.randomUUID()}`;
    const headers = {
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
        "X-Tenant-ID": tenantId,
        "X-Service-Name": "mock-customs-smoke"
    };
    const createdResponse = await fetch(`${baseUrl}/runs`, {
        method: "POST",
        headers,
        body: JSON.stringify({
            request_id: requestId,
            session: {
                session_id: `smoke-${mockCaseId}-${Date.now()}`,
                user_id: "smoke-user",
                tenant_id: tenantId
            },
            message: {
                role: "user",
                content: `运行 ${mockCaseId} 一般贸易进口模拟`
            },
            business_context: { mock_case_id: mockCaseId },
            options: {
                intent: "mock_import_declaration",
                response_mode: "poll",
                output_file_policy: "none",
                timeout_seconds: 60
            }
        })
    });
    assert.equal(createdResponse.status, 202);
    const created = await createdResponse.json();

    let snapshot;
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
        const response = await fetch(`${baseUrl}/runs/${created.run_id}`, {
            headers
        });
        assert.equal(response.status, 200);
        snapshot = await response.json();
        if (["completed", "failed", "cancelled"].includes(snapshot.status)) break;
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    assert.equal(snapshot.status, "completed");
    assert.equal(snapshot.structured_result.customs_stage, "CLOSED");
    assert.equal(snapshot.structured_result.mock, true);
    assert.ok(snapshot.structured_result.timeline.length >= 13);
    assert.ok(snapshot.structured_result.receipts.length >= 3);

    const eventsResponse = await fetch(
        `${baseUrl}/runs/${created.run_id}/events`,
        { headers: { ...headers, Accept: "text/event-stream" } }
    );
    const eventsText = await eventsResponse.text();
    assert.match(eventsText, /event: customs_process_updated/);
    assert.match(eventsText, /event: agent_completed/);
    if (mockCaseId === "returned_then_release") {
        assert.equal(snapshot.structured_result.declaration_version_count, 2);
        assert.match(eventsText, /"stage":"RETURNED"/);
    }
    if (mockCaseId === "high_risk_inspection") {
        assert.equal(snapshot.structured_result.inspection.result, "MATCHED");
        assert.match(eventsText, /"stage":"PRICE_QUERY"/);
        assert.match(eventsText, /"stage":"INSPECTION_COMPLETED"/);
    }
    console.log(JSON.stringify({
        mock_case_id: mockCaseId,
        run_id: created.run_id,
        business_case_id: snapshot.structured_result.business_case_id,
        stage: snapshot.structured_result.customs_stage
    }));
}
