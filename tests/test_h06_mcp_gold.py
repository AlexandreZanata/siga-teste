"""H06: gold agentivo em formato de treino (docs/19). Só stdlib, offline."""

from __future__ import annotations

import json

import pytest

from training.export_mcp_gold import export_gold, gold_to_needle, save_splits


def _task(date="2019-05-01"):
    return {
        "method": "siga.locate",
        "args": {"query": "q"},
        "holdout_date": date,
        "ground_truth": {"files": ["a.java"], "commits": []},
    }


def _rec(tid="t1:teacher", query="q", files=None):
    return {
        "id": tid,
        "query": query,
        "tools": ["siga.locate"],
        "answers": {"files": files or ["a.java"], "symbols": []},
        "verification": {"verdict": "exact", "recall_at_k": 1.0, "precision": 1.0},
        "teacher": "teacher",
        "source": "run.jsonl",
        "source_holdout_id": "h-1",
        "difficulty": "easy",
    }


def test_gold_to_needle_direto():
    rec = gold_to_needle(_rec(query="ache x"), {"method": "siga.locate", "args": {"query": "ache x"}})
    assert rec["answers"] == [{"name": "siga.locate", "arguments": {"query": "ache x"}}]
    assert rec["system"].startswith("date:")


def test_formato_needle_e_split_temporal():
    tasks = {"t1": _task("2019-05-01"), "t2": _task("2022-07-14")}
    splits = export_gold([_rec("t1:x"), _rec("t2:x", query="w")], tasks)
    assert [r["query"] for r in splits["train"]] == ["q"]
    assert [r["query"] for r in splits["valid"]] == ["w"]
    rec = splits["train"][0]
    assert set(rec) >= {"query", "tools", "answers", "reasoning", "system"}
    assert rec["answers"] == [{"name": "siga.locate", "arguments": {"query": "q"}}]
    assert "verifier=exact" in rec["reasoning"] and "LLM" not in json.dumps(rec)


def test_gold_fora_do_congelado_aborta():
    with pytest.raises(ValueError):
        export_gold([_rec("fantasma:x")], {"t1": _task()})


def test_manifest_com_hashes_recalculaveis(tmp_path):
    splits = export_gold([_rec("t1:x")], {"t1": _task()})
    manifest = save_splits(splits, tmp_path)
    assert manifest["train_records"] == 1 and manifest["bench_derived"] is True
    for name in ("needle_train", "needle_val", "needle_full"):
        text = (tmp_path / f"{name}.jsonl").read_text(encoding="utf-8")
        import hashlib

        assert manifest["hashes"][name] == hashlib.sha256(text.encode()).hexdigest()
