"""Testes herméticos do harness B1/B2 real (P13-T03, docs/22 §6–§7).

Nenhum teste carrega engine nativa, GPU, pesos reais, o clone do SIGA ou as
tools do projeto: o engine é um fake injetado por `needle_module` e as tools
são funções sintéticas que registram execução. A prova com engine/pesos reais
acontece apenas no run da tarefa (orçamento e checkpoint registrados).
"""

from __future__ import annotations

import json
from pathlib import Path
import time
import types

import pytest

from evaluation import real_needle_eval as harness
from inference.needle_real import RealNeedleModel, validate_arguments

LOCATE_SCHEMA = {
    "name": "siga_locate",
    "description": "localiza",
    "parameters": {
        "type": "object",
        "required": ["query"],
        "additionalProperties": False,
        "properties": {
            "query": {"type": "string"},
            "kind": {"type": ["string", "null"], "enum": ["file", None]},
            "limit": {"type": "integer", "minimum": 1},
        },
    },
}
TRACE_SCHEMA = {
    "name": "siga_trace",
    "description": "traça",
    "parameters": {
        "type": "object",
        "required": ["symbol"],
        "additionalProperties": False,
        "properties": {
            "symbol": {"type": "string"},
            "depth": {"type": "integer", "minimum": 1, "maximum": 3},
        },
    },
}
TOOLS = [LOCATE_SCHEMA, TRACE_SCHEMA]


class FakeNeedle:
    """Engine fake: registra chamadas e executa callables registrados."""

    def __init__(self, weights=None, tools=None, system=None) -> None:
        self.weights = weights
        self.tools = list(tools or [])
        self.system = system
        self.complete_calls: list[dict] = []
        self.run_calls: list[dict] = []
        self.plan: list = []
        self.closed = False

    def complete(self, text, max_new_tokens=512):
        self.complete_calls.append({"text": text, "max_new_tokens": max_new_tokens})
        step = self.plan.pop(0) if self.plan else {"type": "answer", "function_calls": []}
        return step() if callable(step) else step

    def run(self, query, max_steps=8, max_new_tokens=512, strict=True):
        self.run_calls.append(
            {"query": query, "max_steps": max_steps, "max_new_tokens": max_new_tokens}
        )
        functions = {}
        for tool in self.tools:
            schema = getattr(tool, "_needle_tool", None)
            if isinstance(schema, dict):
                functions[schema["name"]] = tool
        sequence = self.plan.pop(0) if self.plan else []
        results = []
        for name, arguments in sequence:
            function = functions.get(name)
            results.append(function(**arguments) if function else {"error": f"unknown tool: {name}"})
        return {"type": "answer", "function_calls": [], "results": results}

    def close(self):
        self.closed = True


def _model(tmp_path: Path, plan=None, tools=None, timeout: float = 120.0) -> RealNeedleModel:
    weights = tmp_path / "fake.cact"
    weights.write_bytes(b"pesos-fake")
    module = types.SimpleNamespace(Needle=FakeNeedle)
    model = RealNeedleModel(
        weights, tools=tools if tools is not None else TOOLS,
        needle_module=module, task_timeout_s=timeout,
    )
    model._engine.plan = list(plan or [])
    return model


def _task(task_id: str, query: str, tool=None, arguments=None, sequence=None) -> dict:
    return {
        "id": task_id,
        "query": query,
        "expected_tool": tool,
        "expected_arguments": arguments or {},
        "expected_sequence": sequence if sequence is not None else ([tool] if tool else []),
        "task_type": "no-tool" if tool is None else "tool",
    }


def _call(name: str, arguments: dict) -> dict:
    return {"type": "call", "function_calls": [{"name": name, "arguments": arguments}]}


def _empty_response() -> dict:
    return {"type": "answer", "function_calls": []}


@pytest.mark.parametrize(
    "schema,arguments,valid",
    [
        (LOCATE_SCHEMA["parameters"], {"query": "Foo"}, True),
        (LOCATE_SCHEMA["parameters"], {}, False),  # required ausente
        (LOCATE_SCHEMA["parameters"], {"query": "Foo", "extra": 1}, False),  # extra
        (LOCATE_SCHEMA["parameters"], {"query": 7}, False),  # tipo errado
        (LOCATE_SCHEMA["parameters"], {"query": "Foo", "kind": None}, True),  # null no enum
        (LOCATE_SCHEMA["parameters"], {"query": "Foo", "kind": "nope"}, False),  # fora do enum
        (LOCATE_SCHEMA["parameters"], {"query": "Foo", "limit": True}, False),  # bool não é int
        (LOCATE_SCHEMA["parameters"], {"query": "Foo", "limit": 0}, False),  # minimum
        (TRACE_SCHEMA["parameters"], {"symbol": "X", "depth": 4}, False),  # maximum
        (TRACE_SCHEMA["parameters"], {"symbol": "X", "depth": 2}, True),
    ],
)
def test_validate_arguments_full_schema(schema, arguments, valid):
    errors = validate_arguments(schema, arguments)
    assert (not errors) is valid, errors


def test_validate_arguments_items_min_and_max(tmp_path):
    parameters = {
        "type": "object",
        "required": ["symbols", "task"],
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "task": {"type": "string"},
        },
        "additionalProperties": False,
    }
    assert validate_arguments(parameters, {"symbols": ["A"], "task": "t"}) == []
    assert validate_arguments(parameters, {"symbols": [], "task": "t"})
    assert validate_arguments(parameters, {"symbols": [1], "task": "t"})
    assert validate_arguments(parameters, {"symbols": ["A"], "task": "t", "x": 1})


def test_b1_uses_single_generation_and_keeps_labels_out_of_prompt(tmp_path):
    query = "Localize o controller ExDocumentoController"
    task = _task("val-000", query, "siga_trace", {"symbol": "ExDocumentoController"})
    model = _model(tmp_path, plan=[_call("siga_locate", {"query": "ExDocumentoController"})])

    result = harness.run_b1(model, [task], budget_s=None, progress=False)

    assert result["status"] == "completed"
    assert len(model._engine.complete_calls) == 1  # uma única geração
    assert model._engine.run_calls == []  # B1 nunca executa tools
    assert model._engine.complete_calls[0]["text"] == query  # só a query vai ao engine
    prediction = result["predictions"][0]
    assert prediction["tool"] == "siga_locate"
    assert prediction["expected_tool"] == "siga_trace"  # label existe só no scorer
    assert prediction["generations"] == 1
    assert prediction["schema_valid"] is True
    metrics = harness.summarize_b1(result["predictions"])
    assert metrics["tool_selection_accuracy"] == 0.0  # locate != trace
    assert metrics["generations_max"] == 1


def test_b1_escalates_truncated_envelope_once(tmp_path):
    def truncated():
        raise RuntimeError("engine returned an unparseable envelope (boom); engine bug")

    model = _model(
        tmp_path,
        plan=[truncated, _call("siga_locate", {"query": "Foo"})],
    )
    result = harness.run_b1(
        model, [_task("val-000", "Localize Foo", "siga_locate")], budget_s=None, progress=False
    )
    prediction = result["predictions"][0]
    assert prediction["escalated"] is True
    assert prediction["truncated"] is False
    assert prediction["generations"] == 2
    assert [call["max_new_tokens"] for call in model._engine.complete_calls] == [128, 256]
    assert prediction["schema_valid"] is True


def test_b1_escalates_engine_reported_truncation(tmp_path):
    truncated = {
        "type": "call",
        "function_calls": [],
        "error": "tool call truncated: token budget exhausted",
        "error_code": "truncated",
    }
    model = _model(
        tmp_path,
        plan=[truncated, _call("siga_locate", {"query": "Foo"})],
    )
    result = harness.run_b1(
        model, [_task("val-000", "Localize Foo", "siga_locate")], budget_s=None, progress=False
    )
    prediction = result["predictions"][0]
    assert prediction["escalated"] is True
    assert prediction["truncated"] is False
    assert prediction["max_new_tokens"] == 256
    assert prediction["generations"] == 2
    assert [call["max_new_tokens"] for call in model._engine.complete_calls] == [128, 256]
    assert prediction["schema_valid"] is True


def test_b1_timeout_aborts_and_preserves_checkpoint(tmp_path):
    def slow():
        time.sleep(0.5)
        return _empty_response()

    checkpoint = tmp_path / "b1.partial.jsonl"
    model = _model(tmp_path, plan=[slow, _call("siga_trace", {"symbol": "X"})], timeout=0.05)
    tasks = [
        _task("val-000", "consulta lenta", "siga_locate"),
        _task("val-001", "segunda consulta", "siga_trace"),
    ]
    result = harness.run_b1(
        model, tasks, checkpoint=checkpoint, budget_s=None, progress=False
    )

    assert result["status"] == "aborted_timeout"
    assert len(result["predictions"]) == 1
    assert result["predictions"][0]["timeout"] is True
    assert len(model._engine.complete_calls) == 1  # segunda tarefa não iniciou
    lines = [json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines()]
    assert [line["task_id"] for line in lines] == ["val-000"]


def test_b1_checkpoint_resume_skips_done_tasks(tmp_path):
    checkpoint = tmp_path / "b1.partial.jsonl"
    tasks = [
        _task("val-000", "Localize Foo", "siga_locate", {"query": "Foo"}),
        _task("val-001", "Toque Bar", "siga_trace", {"symbol": "Bar"}),
    ]
    first = _model(
        tmp_path,
        plan=[
            _call("siga_locate", {"query": "Foo"}),
            _call("siga_trace", {"symbol": "Bar"}),
        ],
    )
    first_result = harness.run_b1(
        first, tasks, checkpoint=checkpoint, budget_s=None, progress=False
    )
    assert first_result["status"] == "completed"
    assert len(first_result["predictions"]) == 2

    resume = _model(tmp_path, plan=[_empty_response()])
    resume_result = harness.run_b1(
        resume, tasks, checkpoint=checkpoint, budget_s=None, progress=False
    )
    assert len(resume._engine.complete_calls) == 0  # resume idempotente
    assert [p["task_id"] for p in resume_result["predictions"]] == ["val-000", "val-001"]
    assert resume_result["status"] == "completed"


def test_b1_projection_abort_stops_early(tmp_path):
    model = _model(
        tmp_path,
        plan=[
            _call("siga_locate", {"query": "A"}),
            _call("siga_locate", {"query": "B"}),
            _call("siga_locate", {"query": "C"}),
        ],
    )
    tasks = [_task(f"val-{i:03d}", f"consulta {i}", "siga_locate") for i in range(3)]
    result = harness.run_b1(model, tasks, budget_s=0.000001, progress=False)
    assert result["status"] == "aborted_projection"
    assert len(result["predictions"]) == 1
    assert "projeção" in result["abort_reason"]


def test_summarize_b1_metrics():
    predictions = [
        {
            "task_id": "val-000",
            "expected_tool": "siga_locate",
            "arguments": {"query": "Foo"},
            "expected_arguments": {"query": "Foo"},
            "tool": "siga_locate",
            "schema_valid": True,
            "is_invalid_call": False,
            "grounding_violations": [],
            "generations": 1,
            "latency_ms": 10.0,
        },
        {
            "task_id": "val-001",
            "expected_tool": "siga_trace",
            "arguments": {"symbol": "Bar"},
            "expected_arguments": {"symbol": "Bar"},
            "tool": "siga_locate",
            "schema_valid": True,
            "is_invalid_call": False,
            "grounding_violations": ["$..symbol"],
            "generations": 2,
            "latency_ms": 30.0,
        },
        {
            "task_id": "val-002",
            "expected_tool": None,
            "arguments": {},
            "expected_arguments": {},
            "tool": None,
            "schema_valid": True,
            "is_invalid_call": False,
            "grounding_violations": [],
            "generations": 1,
            "latency_ms": 20.0,
        },
    ]
    metrics = harness.summarize_b1(predictions)
    assert metrics["counts"] == {"tasks": 3, "tool_tasks": 2, "no_tool_tasks": 1}
    assert metrics["tool_selection_accuracy"] == 0.5
    assert metrics["argument_exact_match"] == 0.5
    assert metrics["schema_validity_rate"] == 1.0
    assert metrics["invalid_tool_call_rate"] == 0.0
    assert metrics["no_tool_accuracy"] == 1.0
    assert metrics["grounding_clean_rate"] == pytest.approx(2 / 3)
    assert metrics["latency_ms"]["p50"] == 20.0
    assert metrics["generations_max"] == 2


def test_b2_wrapper_executes_real_function_and_logs(tmp_path):
    calls = []
    log: list[dict] = []

    def real_locate(query, repo=None, **kwargs):
        calls.append({"query": query, "repo": repo, "kwargs": kwargs})
        return [{"file": "Foo.java"}]

    wrapper = harness._make_wrapper(LOCATE_SCHEMA, real_locate, log, repo="/clone")
    assert wrapper(query="Foo", limit=3) == [{"file": "Foo.java"}]
    assert calls == [{"query": "Foo", "repo": "/clone", "kwargs": {"limit": 3}}]
    assert log == [{"name": "siga_locate", "arguments": {"query": "Foo", "limit": 3}, "ok": True}]


def test_b2_wrapper_records_real_tool_error(tmp_path):
    log: list[dict] = []

    def broken(query, repo=None):
        raise ValueError("símbolo inválido")

    wrapper = harness._make_wrapper(LOCATE_SCHEMA, broken, log, repo=None)
    with pytest.raises(ValueError):
        wrapper(query="Foo")
    assert log[0]["error"].startswith("ValueError")


def test_b2_uses_registered_callables_and_three_steps(tmp_path):
    executed = []

    def locate_tool(query, repo=None):
        executed.append(query)
        return [{"file": "Foo.java"}]

    locate_tool._needle_tool = LOCATE_SCHEMA
    tool_log: list[dict] = []
    wrapper = harness._make_wrapper(LOCATE_SCHEMA, locate_tool, tool_log, repo=None)
    model = _model(
        tmp_path, tools=[wrapper], plan=[[("siga_locate", {"query": "Foo"})]]
    )
    task = _task("val-000", "Localize Foo", "siga_locate", {"query": "Foo"})

    result = harness.run_b2(
        model, [task], tool_log, max_steps=3, budget_s=None, progress=False
    )

    assert model._engine.run_calls[0]["max_steps"] == 3
    assert executed == ["Foo"]
    assert result["predictions"][0]["tool_sequence"] == ["siga_locate"]
    metrics = harness.summarize_b2(result["predictions"])
    assert metrics["sequence_success_rate"] == 1.0
    assert metrics["unknown_tool_count"] == 0
    assert metrics["calls_total"] == 1


def test_load_validation_tasks_stratified_and_deterministic(tmp_path):
    path = tmp_path / "val.jsonl"
    records = []
    for index in range(24):
        records.append({"query": f"locate {index}", "answers": [{"name": "siga_locate", "arguments": {"query": f"L{index}"}}]})
    for tool, count in (("siga_trace", 8), ("siga_impact", 8), ("siga_history", 8), ("siga_context", 4)):
        for index in range(count):
            records.append(
                {"query": f"{tool} {index}", "answers": [{"name": tool, "arguments": {}}]}
            )
    for index in range(12):
        records.append({"query": f"off-topic {index}", "answers": []})
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )

    stage = harness.load_validation_tasks(path, stage=16, seed=0)
    assert len(stage) == 16
    assert sum(1 for task in stage if task["expected_tool"] is None) == 2
    assert len({task["id"] for task in stage}) == 16
    assert harness.load_validation_tasks(path, stage=16, seed=0) == stage
    other_seed = harness.load_validation_tasks(path, stage=16, seed=7)
    assert {task["id"] for task in other_seed} == {task["id"] for task in stage}
    assert [task["id"] for task in other_seed] != [task["id"] for task in stage]
    # funil aninhado: o estágio 4 é subconjunto do 16 (prefixo da ordem canônica)
    stage4 = harness.load_validation_tasks(path, stage=4, seed=0)
    assert {task["id"] for task in stage4} <= {task["id"] for task in stage}
    assert sum(1 for task in stage4 if task["expected_tool"] is None) == 1
    assert stage[0]["expected_arguments"] is not None
    with pytest.raises(ValueError):
        harness.load_validation_tasks(path, stage=999, seed=0)


def test_tracked_tools_schema_matches_five_siga_tools():
    schema = json.loads(
        (Path(harness.__file__).resolve().parent.parent / "inference/siga_tools_schema.json")
        .read_text(encoding="utf-8")
    )
    names = [entry["name"] for entry in schema]
    assert names == list(harness.TOOL_ORDER)
    for entry in schema:
        assert entry["parameters"]["type"] == "object"
        assert entry["parameters"]["additionalProperties"] is False


def test_build_report_strips_raw_and_records_provenance(tmp_path):
    result = {
        "status": "completed",
        "abort_reason": None,
        "predictions": [
            {"task_id": "val-000", "raw": {"envelope": "bruto"}, "latency_ms": 1.0}
        ],
        "elapsed_s": 1.5,
        "num_tasks": 1,
        "num_done": 1,
    }
    report = harness.build_report(
        mode="b1",
        label="unit",
        result=result,
        metrics={"counts": {"tasks": 1}},
        weights_path=tmp_path / "fake.cact",
        weights_sha="abc",
        schema_path=None,
        schema_sha=None,
        tasks_path=tmp_path / "val.jsonl",
        tasks_sha="def",
        stage=4,
        seed=0,
        profile={"max_new_tokens": 128},
        preflight_info={"jax": {"backend": "gpu"}},
        checkpoint=tmp_path / "ckpt.jsonl",
        backend_note="engine real",
    )
    assert report["task"] == "P13-T03"
    assert report["predictions"][0]["task_id"] == "val-000"
    assert "raw" not in report["predictions"][0]
    assert report["dataset"]["sha256"] == "def"
    assert report["model"]["weights_sha256"] == "abc"
    assert report["metrics"]["counts"] == {"tasks": 1}
