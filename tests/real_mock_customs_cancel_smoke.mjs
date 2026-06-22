import assert from "node:assert/strict";
import crypto from "node:crypto";

const apiBase = "http://127.0.0.1:8000";
const agentBase = `${apiBase}/api/agent/v1`;
const tenantId = "mock-cancel-tenant";
const requestId = `mock-cancel-${crypto.randomUUID()}`;
const sessionId = `mock-cancel-session-${Date.now()}`;
const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": requestId,
    "X-Tenant-ID": tenantId,
    "X-Service-Name": "mock-customs-cancel-smoke"
};

const createdResponse = await fetch(`${agentBase}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
        request_id: requestId,
        session: {
            session_id: sessionId,
            user_id: "mock-cancel-user",
            tenant_id: tenantId
        },
        message: {
            role: "user",
            content: "启动高风险进口报关模拟，然后测试取消。"
        },
        business_context: {
            mock_case_id: "high_risk_inspection",
            step_delay_ms: 500
        },
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

let businessCaseId = "";
const eventsResponse = await fetch(
    `${agentBase}/runs/${created.run_id}/events`,
    { headers: { ...headers, Accept: "text/event-stream" } }
);
assert.equal(eventsResponse.status, 200);
const reader = eventsResponse.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
const deadline = Date.now() + 10000;
while (!businessCaseId && Date.now() < deadline) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    for (const block of buffer.split("\n\n")) {
        const dataLine = block.split("\n").find(line => line.startsWith("data:"));
        if (!dataLine) continue;
        const event = JSON.parse(dataLine.slice(5).trim());
        if (event.event === "customs_process_updated") {
            businessCaseId = event.data.business_case_id;
            break;
        }
    }
}
assert.ok(businessCaseId, "business case was not created");

const cancelResponse = await fetch(
    `${agentBase}/runs/${created.run_id}/cancel`,
    { method: "POST", headers }
);
assert.equal(cancelResponse.status, 200);
assert.equal((await cancelResponse.json()).status, "cancelled");

const runResponse = await fetch(`${agentBase}/runs/${created.run_id}`, { headers });
const run = await runResponse.json();
assert.equal(run.status, "cancelled");

let customsCase;
for (let attempt = 0; attempt < 100; attempt += 1) {
    const caseResponse = await fetch(
        `${apiBase}/internal/customs-simulator/v1/cases/${businessCaseId}`
    );
    assert.equal(caseResponse.status, 200);
    customsCase = await caseResponse.json();
    if (customsCase.stage === "CANCELLED") break;
    await new Promise(resolve => setTimeout(resolve, 20));
}
assert.equal(customsCase.stage, "CANCELLED");
assert.equal(customsCase.timeline.at(-1).event_type, "case_cancelled");

console.log(JSON.stringify({
    run_id: created.run_id,
    business_case_id: businessCaseId,
    run_status: run.status,
    customs_stage: customsCase.stage
}));
