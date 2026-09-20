"""F23: auditoria de dessincronização GT×tools. Hermético, offline."""

from __future__ import annotations

from evaluation.gt_desync import audit, classify


def _task(kind="locate", files=None, commits=None):
    return {
        "kind": kind,
        "method": "siga.locate",
        "args": {},
        "ground_truth": {"files": files or [], "commits": commits or []},
    }


def test_classify_cobre_os_quatro_estados():
    assert classify(_task(files=["a.java"]), {"files": ["a.java"], "commits": []}) == "EXACT"
    assert classify(_task(files=["a.java"]), {"files": ["a.java", "b.java"], "commits": []}) == "SUPERSET_STALE"
    assert classify(_task(files=["a.java", "b.java"]), {"files": ["a.java"], "commits": []}) == "PARTIAL"
    assert classify(_task(files=["a.java"]), {"files": ["z.java"], "commits": []}) == "DISJOINT"


def test_classify_history_por_commits():
    sha = "a" * 40
    t = _task(kind="history", commits=[{"sha": sha}])
    assert classify(t, {"files": [], "commits": [sha]}) == "EXACT"
    assert classify(t, {"files": [], "commits": ["b" * 40]}) == "DISJOINT"


def test_audit_recomenda_refreeze_com_stale_alto(tmp_path, monkeypatch):
    import evaluation.gt_desync as gd

    tasks = {f"t{i}": _task(files=["a.java"]) for i in range(6)}
    monkeypatch.setattr(gd, "current_output", lambda task, siga: {"files": ["a.java", "extra.java"], "commits": []})
    rep = audit(tasks, tmp_path)
    assert rep["n_superset_stale"] == 6
    assert rep["recommendation"] == "RE-FREEZE"
    assert rep["by_kind"]["locate"]["SUPERSET_STALE"] == 6
