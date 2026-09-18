"""F03: os testes que pulam sem o clone do SIGA executam de verdade na fixture.

Espelha, sobre a fixture mínima (tests/siga_fixture.py), a lógica dos
gates reais que dependem do clone: execução determinística dos 100 golds
(P05-T03), fluxo locate→trace→context sem inventar path (P05-T02) e
primitivas determinísticas (P05-T01). No CI, este arquivo roda sempre;
os originais continuam pulando até o clone existir no runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from indexer import git_history
from tools import primitives, simulator
from tools.siga_context import siga_context
from tools.siga_locate import siga_locate
from tools.siga_trace import siga_trace

GOLD_FILE = Path(__file__).resolve().parent.parent.parent / "tools/gold_trajectories.jsonl"


@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tests.siga_fixture import build_siga_fixture

    return build_siga_fixture(tmp_path_factory.mktemp("siga-fixture-golds"))


def test_100_gold_trajectories_execute_deterministically_on_fixture(fixture_root: Path):
    golds = simulator.load_trajectories(GOLD_FILE)
    sim = simulator.Simulator(repo=fixture_root)
    summary = sim.run_all(golds)

    assert summary["total"] == 100
    assert summary["failed"] == 0, f"Falhas na execução dos golds: {summary['failed_ids']}"
    assert summary["success"] == 100
    assert summary["success_rate"] == 1.0
    assert summary["total_steps"] >= 100


def test_semantic_tools_flow_without_invented_paths_on_fixture(fixture_root: Path):
    candidates = siga_locate("calcular tramites pendentes", repo=fixture_root, limit=5)
    assert candidates, "deve localizar candidatos na fixture"
    for c in candidates:
        if c.get("file"):
            assert Path(c["file"]).is_file(), f"arquivo inexistente: {c['file']}"

    trace_res = siga_trace("ExTramiteBL", depth=1, repo=fixture_root)
    assert trace_res["symbol"] == "ExTramiteBL"
    for f in trace_res["files"]:
        assert Path(f).is_file()

    capsule = siga_context(
        symbols=["ExTramiteBL"],
        task="Ajustar cálculo de trâmites pendentes",
        repo=fixture_root,
    )
    assert "ExTramiteBL" in capsule["capsule_text"]
    for f in capsule["files"]:
        assert Path(f).is_file()


def test_primitives_and_git_history_on_fixture(fixture_root: Path):
    files = primitives.find_file(repo=str(fixture_root), pattern="ExDocumentoController.java", limit=5)
    assert any(f.endswith("ExDocumentoController.java") for f in files)
    assert all(Path(f).is_file() for f in files)

    hits = primitives.search_text(repo=str(fixture_root), pattern="calcularTramitesPendentes", limit=5)
    assert any("ExTramiteBL.java" in h["file"] for h in hits)

    refs = primitives.find_references(repo=str(fixture_root), symbol="ExTramiteBL", limit=5)
    assert refs

    outline_data = primitives.get_file_outline(
        file=str(fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java")
    )
    assert outline_data["package"] == "br.gov.jfrj.siga.ex.bl"

    commits = git_history.recent_commits(fixture_root, limit=5)
    assert len(commits) >= 1
    assert len(commits[0]["sha"]) == 40
    assert git_history.files_in_commit(fixture_root, commits[0]["sha"])
