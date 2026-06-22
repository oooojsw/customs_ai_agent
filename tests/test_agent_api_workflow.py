import asyncio

from fastapi import FastAPI

from src.agent_api.adapters import (
    AdapterResult,
    DemoFullReviewAdapter,
    ExecutionContext,
    FullReviewAdapter,
    ReportAdapter,
)
from src.agent_api.events import EventEmitter
from src.agent_api.models import (
    AgentOutput,
    CreateRunRequest,
    OutputKind,
)
from src.agent_api.outputs import LocalOutputRegistry, OutputManager
from src.agent_api.store import InMemoryRunStore


def make_request(intent="full_review"):
    return CreateRunRequest.model_validate(
        {
            "request_id": f"req-{intent}-001",
            "session": {
                "session_id": "session-001",
                "user_id": "user-001",
                "tenant_id": "tenant-001",
            },
            "message": {"content": "审查并生成报告"},
            "options": {
                "intent": intent,
                "output_file_policy": "agent_temporary",
            },
        }
    )


def test_report_adapter_generates_docx_output(tmp_path):
    class FakeReporter:
        def __init__(self, **kwargs):
            self.report_text_buffer = ""

        async def generate_stream(self, *args, **kwargs):
            self.report_text_buffer = "# 合规结论\n- 建议复核 HS 编码"
            yield 'data: {"type":"step_start","payload":{"title":"撰写结论"}}\n\n'
            yield 'data: {"type":"done","payload":{}}\n\n'

    async def scenario():
        request = make_request("report")
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        app = FastAPI()
        app.state.reporter = FakeReporter()
        app.state.kb = None
        app.state.llm_config = {}
        output_manager = OutputManager(
            LocalOutputRegistry(tmp_path / "outputs")
        )
        result = await ReportAdapter().execute(
            request,
            app,
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(output_manager=output_manager),
        )
        assert result.final_answer == "合规建议书已生成。"
        assert result.outputs[0].kind == OutputKind.DOCUMENT
        assert result.outputs[0].format == "docx"

    asyncio.run(scenario())


def test_full_review_merges_pipeline_results():
    calls = []

    class FakeStage:
        def __init__(self, name, result):
            self.name = name
            self.result = result

        async def execute(self, request, app, emitter, context):
            calls.append(self.name)
            return self.result

    async def scenario():
        request = make_request()
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        report_output = AgentOutput(
            output_id="out-report",
            kind=OutputKind.DOCUMENT,
            format="docx",
            name="report.docx",
        )
        adapter = FullReviewAdapter(
            ocr=FakeStage("ocr", AdapterResult(final_answer="ocr")),
            declaration=FakeStage(
                "declaration",
                AdapterResult(
                    final_answer="query",
                    structured_result={
                        "declaration_text": "HS编码 85423100"
                    },
                ),
            ),
            audit=FakeStage(
                "audit",
                AdapterResult(
                    final_answer="建议复核",
                    structured_result={"findings": [{"code": "HS"}]},
                ),
            ),
            regulations=FakeStage(
                "regulations",
                AdapterResult(
                    final_answer="找到 1 条依据",
                    structured_result={"citations": [{"source": "rule"}]},
                ),
            ),
            report=FakeStage(
                "report",
                AdapterResult(
                    final_answer="报告已生成",
                    structured_result={"character_count": 100},
                    outputs=[report_output],
                ),
            ),
        )
        result = await adapter.execute(
            request,
            FastAPI(),
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(),
        )
        assert calls == ["audit", "regulations", "report"]
        assert result.outputs == [report_output]
        assert result.structured_result["audit"]["findings"][0]["code"] == "HS"

    asyncio.run(scenario())


def test_demo_full_review_accepts_entry_id_only_and_creates_docx(tmp_path):
    async def scenario():
        request = CreateRunRequest.model_validate(
            {
                "request_id": "req-demo-entry-only-001",
                "session": {
                    "session_id": "session-demo-001",
                    "user_id": "platform-user-001",
                    "tenant_id": "tenant-001",
                },
                "message": {"content": ""},
                "business_context": {
                    "entry_id": "530120250001",
                    "mock_mode": True,
                },
                "options": {
                    "intent": "full_review",
                    "output_file_policy": "agent_temporary",
                },
            }
        )
        store = InMemoryRunStore()
        snapshot, _ = await store.create(request)
        output_manager = OutputManager(
            LocalOutputRegistry(tmp_path / "outputs")
        )
        result = await DemoFullReviewAdapter().execute(
            request,
            FastAPI(),
            EventEmitter(store, snapshot.run_id),
            ExecutionContext(output_manager=output_manager),
        )

        docx_output = next(
            output for output in result.outputs if output.kind == OutputKind.DOCUMENT
        )
        assert "演示审单完成" in result.final_answer
        assert result.structured_result["process"]["state"] == "review_recommended"
        assert docx_output.agent_output_url.endswith("/content")
        assert output_manager.local_registry.get_path(docx_output.output_id).is_file()

    asyncio.run(scenario())
