import assert from "node:assert/strict";
import crypto from "node:crypto";

const baseUrl = "http://127.0.0.1:8000/api/agent/v1";
const requestId = `cancel-smoke-${crypto.randomUUID()}`;
const tenantId = "web-demo";
const headers = {
    "Content-Type": "application/json",
    "X-Request-ID": requestId,
    "X-Tenant-ID": tenantId,
    "X-Service-Name": "cancel-smoke"
};

const createResponse = await fetch(`${baseUrl}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
        request_id: requestId,
        session: {
            session_id: `cancel-session-${Date.now()}`,
            user_id: "cancel-smoke-user",
            tenant_id: tenantId
        },
        message: {
            role: "user",
            content: "调用 OpenCode 子代理执行一个长任务，用于测试停止功能。"
        },
        options: {
            intent: "auto",
            response_mode: "stream",
            timeout_seconds: 600
        }
    })
});
assert.equal(createResponse.status, 202);
const run = await createResponse.json();

const eventResponse = await fetch(`${baseUrl}/runs/${run.run_id}/events`, {
    headers: {
        "Accept": "text/event-stream",
        "X-Request-ID": requestId,
        "X-Tenant-ID": tenantId,
        "X-Service-Name": "cancel-smoke"
    }
});
assert.equal(eventResponse.status, 200);

const reader = eventResponse.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
let cancelSent = false;
let cancelledEventSeen = false;
const deadline = Date.now() + 30000;

async function readWithTimeout(timeoutMs) {
    let timeoutId;
    try {
        return await Promise.race([
            reader.read(),
            new Promise((_, reject) => {
                timeoutId = setTimeout(
                    () => reject(new Error("SSE read timed out")),
                    timeoutMs
                );
            })
        ]);
    } finally {
        clearTimeout(timeoutId);
    }
}

while (Date.now() < deadline && !cancelledEventSeen) {
    const readResult = await readWithTimeout(Math.max(1, deadline - Date.now()));
    if (readResult.done) break;
    buffer += decoder.decode(readResult.value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";

    for (const block of blocks) {
        const dataLine = block.split("\n").find(line => line.startsWith("data:"));
        if (!dataLine) continue;
        const event = JSON.parse(dataLine.slice(5).trim());
        if (event.event === "tool_started" && !cancelSent) {
            cancelSent = true;
            const cancelResponse = await fetch(
                `${baseUrl}/runs/${run.run_id}/cancel`,
                { method: "POST", headers }
            );
            assert.equal(cancelResponse.status, 200);
            const cancelled = await cancelResponse.json();
            assert.equal(cancelled.status, "cancelled");
        }
        if (event.event === "agent_cancelled") cancelledEventSeen = true;
    }
}

assert.equal(cancelSent, true, "cancel request was not sent after tool start");
assert.equal(cancelledEventSeen, true, "agent_cancelled event was not received");

const statusResponse = await fetch(`${baseUrl}/runs/${run.run_id}`, { headers });
const snapshot = await statusResponse.json();
assert.equal(snapshot.status, "cancelled");
console.log(JSON.stringify({ run_id: run.run_id, status: snapshot.status }));
