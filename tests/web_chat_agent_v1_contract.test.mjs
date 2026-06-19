import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import vm from "node:vm";

const storage = new Map();
const createStorage = () => ({
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value))
});

let capturedRequest = null;
const context = vm.createContext({
    console,
    window: {
        crypto,
        currentLanguage: "zh"
    },
    sessionStorage: createStorage(),
    localStorage: createStorage(),
    document: { getElementById: () => null },
    fetch: async (url, options) => {
        capturedRequest = { url, options };
        return {
            ok: true,
            status: 202,
            json: async () => ({
                run_id: "run-contract",
                request_id: "request-contract",
                status: "queued",
                events_url: "/api/agent/v1/runs/run-contract/events",
                status_url: "/api/agent/v1/runs/run-contract"
            })
        };
    },
    setTimeout,
    clearTimeout,
    AbortController,
    URL,
    Map,
    Math,
    Date
});

const configSource = fs.readFileSync("web/js/config.js", "utf8");
const chatSource = fs.readFileSync("web/js/chat.js", "utf8");
vm.runInContext(configSource, context, { filename: "web/js/config.js" });
vm.runInContext(chatSource, context, { filename: "web/js/chat.js" });

const created = await vm.runInContext(
    'createChatAgentRun("只审单，不要计算税费")',
    context
);

assert.equal(created.run_id, "run-contract");
assert.equal(
    capturedRequest.url,
    "http://127.0.0.1:8000/api/agent/v1/runs"
);
assert.equal(capturedRequest.options.method, "POST");

const body = JSON.parse(capturedRequest.options.body);
assert.equal(body.message.content, "只审单，不要计算税费");
assert.equal(body.options.intent, "auto");
assert.equal(body.options.response_mode, "stream");
assert.equal(body.options.output_file_policy, "agent_temporary");
assert.equal(body.session.user_id, "web-demo-user");
assert.equal(body.session.tenant_id, "web-demo");
assert.ok(body.session.session_id.startsWith("web-session-"));
assert.ok(body.request_id.startsWith("web-"));

const mappedTool = vm.runInContext(
    `mapAgentEventToLegacyEvent({
        event: "tool_started",
        data: { tool: "audit_declaration", display_name: "智能审单" }
    })`,
    context
);
assert.equal(mappedTool.type, "tool_start");
assert.equal(mappedTool.tool_name, "audit_declaration");

const parsedEvent = vm.runInContext(
    `parseAgentSseBlock(
        'id: 3\\nevent: message_delta\\ndata: {"event":"message_delta","data":{"content":"完成"}}'
    )`,
    context
);
assert.equal(parsedEvent.event, "message_delta");
assert.equal(parsedEvent.data.content, "完成");

await vm.runInContext(
    'requestChatAgentCancellation("run-contract", "request-contract")',
    context
);
assert.equal(
    capturedRequest.url,
    "http://127.0.0.1:8000/api/agent/v1/runs/run-contract/cancel"
);
assert.equal(capturedRequest.options.method, "POST");
assert.equal(capturedRequest.options.headers["X-Tenant-ID"], "web-demo");

const streamController = new AbortController();
context.streamController = streamController;
await vm.runInContext(`
    activeChatRun = {
        runId: "run-contract",
        requestId: "request-contract",
        cancellationRequested: false,
        streamController
    };
    stopChatAgent();
`, context);
assert.equal(streamController.signal.aborted, true);

console.log("web chat Agent V1 contract passed");
