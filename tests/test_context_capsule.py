"""Testes unitários da Context Capsule e comparação JSON vs Texto (P09-T01, docs/04 §ADR-008).

Verifica:
1. Estrutura completa da cápsula (TASK INTERPRETATION, PRIMARY SYMBOLS file::symbol,
   FLOW A->B->C, RELATED FILES, DOMAIN, PERSISTENCE, VIEWS, MIGRATIONS, TESTS,
   SIMILAR COMMITS, SNIPPETS sem prosa).
2. Serialização idêntica nos formatos JSON e Texto Compacto.
3. Métricas de redução efetiva de tokens (effective_token_reduction >= 85%).
4. Economia de tokens do formato texto compacto em relação ao JSON.
5. Invariante de qualidade semântica: task_success_delta >= 0.0.
6. Fragmentação PT-BR do tokenizer BPE cl100k.
"""

from __future__ import annotations

import json
from pathlib import Path

from context.capsule import (
    CodeSnippet,
    ContextCapsule,
    build_context_capsule,
    calculate_cost_usd,
    calculate_token_reduction,
    compare_capsule_formats,
    count_tokens,
    count_tokens_whitespace,
)
from tools.siga_context import siga_context


def test_capsule_dataclass_and_serialization():
    snip = CodeSnippet(
        file="siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java",
        symbol="ExDocumento",
        lines="L100-L115",
        content="public class ExDocumento extends AbstractExDocumento {\n    private Long id;\n}",
    )
    capsule = ContextCapsule(
        task="Ajustar validação de documento sobrestado",
        task_interpretation="Targeted modification: Validação de sobrestamento no documento",
        primary_symbols=["siga-ex/.../ExDocumento.java::ExDocumento"],
        flow=["ExDocumentoController -> ExBL -> ExDocumento"],
        related_files=["siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java"],
        domain=["ExDocumento"],
        persistence=["ExDao"],
        views=["sigaex/WebContent/paginas/expediente/edita.jsp"],
        migrations=["siga-ex/.../V58_0__RestringirAcesso.sql"],
        tests=["siga-ex/src/test/java/ExBLTest.java"],
        similar_commits=[{"sha": "03487295", "subject": "Não permite apensar sobrestado"}],
        snippets=[snip],
    )

    # 1. to_dict
    d = capsule.to_dict()
    assert d["task"] == "Ajustar validação de documento sobrestado"
    assert d["primary_symbols"] == ["siga-ex/.../ExDocumento.java::ExDocumento"]
    assert len(d["snippets"]) == 1
    assert d["snippets"][0]["symbol"] == "ExDocumento"

    # 2. to_json
    j_compact = capsule.to_json(compact=True)
    parsed = json.loads(j_compact)
    assert parsed["domain"] == ["ExDocumento"]
    assert parsed["flow"] == ["ExDocumentoController -> ExBL -> ExDocumento"]

    # 3. to_compact_text
    txt = capsule.to_compact_text()
    assert "=== CONTEXT CAPSULE ===" in txt
    assert "[TASK INTERPRETATION]" in txt
    assert "[PRIMARY SYMBOLS]" in txt
    assert "- siga-ex/.../ExDocumento.java::ExDocumento" in txt
    assert "[FLOW]" in txt
    assert "- ExDocumentoController -> ExBL -> ExDocumento" in txt
    assert "[DOMAIN]" in txt
    assert "[PERSISTENCE]" in txt
    assert "[VIEWS]" in txt
    assert "[MIGRATIONS]" in txt
    assert "[TESTS]" in txt
    assert "[SIMILAR COMMITS]" in txt
    assert "[SNIPPETS]" in txt
    assert "--- siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java::ExDocumento (L100-L115) ---" in txt
    assert "========================" in txt


def test_capsule_builder_heuristics(tmp_path: Path):
    # Cria estrutura sintética de arquivos
    (tmp_path / "siga-ex/model").mkdir(parents=True)
    (tmp_path / "sigaex/controller").mkdir(parents=True)
    (tmp_path / "sigaex/views").mkdir(parents=True)
    (tmp_path / "siga-ex/migration").mkdir(parents=True)
    (tmp_path / "siga-ex/test").mkdir(parents=True)

    f_ent = tmp_path / "siga-ex/model/ExDocumento.java"
    f_ent.write_text("package siga.model;\npublic class ExDocumento {}\n", encoding="utf-8")

    f_ctrl = tmp_path / "sigaex/controller/ExDocumentoController.java"
    f_ctrl.write_text("package siga.controller;\npublic class ExDocumentoController {}\n", encoding="utf-8")

    f_jsp = tmp_path / "sigaex/views/edita.jsp"
    f_jsp.write_text("<html><%@ taglib %></html>\n", encoding="utf-8")

    f_sql = tmp_path / "siga-ex/migration/V1__init.sql"
    f_sql.write_text("CREATE TABLE EX_DOCUMENTO (ID NUMBER);\n", encoding="utf-8")

    f_test = tmp_path / "siga-ex/test/ExDocumentoTest.java"
    f_test.write_text("public class ExDocumentoTest {}\n", encoding="utf-8")

    capsule = build_context_capsule(
        task="Refatorar criação de documento",
        repo=tmp_path,
        files=[str(f_ent), str(f_ctrl), str(f_jsp), str(f_sql), str(f_test)],
        symbols=["ExDocumento", "ExDocumentoController"],
    )

    assert "ExDocumento" in capsule.domain
    assert any("edita.jsp" in v for v in capsule.views)
    assert any("V1__init.sql" in m for m in capsule.migrations)
    assert any("ExDocumentoTest.java" in t for t in capsule.tests)
    assert any("ExDocumentoController" in ps for ps in capsule.primary_symbols)
    assert any("::ExDocumento" in ps for ps in capsule.primary_symbols)
    assert len(capsule.flow) >= 1
    assert "ExDocumentoController" in capsule.flow[0]


def test_token_counting_and_reduction():
    short_text = "public class ExBL { void gravar() {} }"
    long_raw_code = "\n".join([f"    // line {i} of 5000 lines of boilerplate" for i in range(5000)])

    tokens_short = count_tokens(short_text)
    tokens_long = count_tokens(long_raw_code)

    assert tokens_short > 0
    assert tokens_long > 5000

    reduction = calculate_token_reduction(tokens_short, tokens_long)
    assert reduction > 0.95  # >95% de redução

    # Edge cases
    assert calculate_token_reduction(0, 1000) == 1.0
    assert calculate_token_reduction(1000, 0) == 0.0
    assert calculate_cost_usd(1000, price_per_1k=0.003) == 0.003


def test_text_vs_json_efficiency():
    capsule = ContextCapsule(
        task="Alteração para contemplar o arquivamento automatico",
        task_interpretation="Targeted modification/investigation: Arquivamento automático",
        primary_symbols=[
            "sigaex/src/main/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java::ExDocumentoController",
            "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java::ExBL",
        ],
        flow=["ExDocumentoController -> ExBL -> ExDocumento"],
        related_files=[
            "sigaex/src/main/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java",
            "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java",
        ],
        domain=["ExDocumento"],
        persistence=["ExDao"],
        views=["sigaex/WebContent/paginas/expediente/edita.jsp"],
        migrations=["siga-ex/src/main/resources/db/migration/V1.sql"],
        tests=["siga-ex/src/test/java/ExBLTest.java"],
        similar_commits=[{"sha": "163c158f", "subject": "Arquivamento automatico"}],
        snippets=[
            CodeSnippet(
                file="sigaex/.../ExDocumentoController.java",
                symbol="ExDocumentoController",
                lines="L45-L65",
                content=(
                    "public class ExDocumentoController extends SigaController {\n"
                    "    private ExBL bl;\n"
                    "    public void arquivar(Long id) {\n"
                    "        ExDocumento doc = bl.buscarPorId(id);\n"
                    "        bl.arquivar(doc);\n"
                    "    }\n"
                    "    public void desarquivar(Long id) {\n"
                    "        bl.desarquivar(id);\n"
                    "    }\n"
                    "}"
                ),
            )
        ],
    )

    j_tokens = capsule.token_count_json(compact=False)
    t_tokens = capsule.token_count()

    # Formato de texto compacto deve ser estritamente mais eficiente em tokens que o JSON
    assert t_tokens < j_tokens
    savings_pct = (1.0 - t_tokens / j_tokens) * 100
    assert savings_pct > 5.0, f"economia esperada >5%, obtido: {savings_pct:.2f}%"


def test_portuguese_tokenizer_fragmentation():
    pt_query = "Não permite apensar a um documento sobrestado e cancela transferência externa."
    bpe_toks = count_tokens(pt_query)
    ws_toks = count_tokens_whitespace(pt_query)

    ratio = bpe_toks / ws_toks
    # Conforme ADRs (docs/00 e docs/03), PT-BR fragmenta em ~1.7x
    assert 1.4 <= ratio <= 2.5, f"ratio de fragmentação PT-BR fora do esperado: {ratio}"


def test_compare_capsule_formats_smoke():
    res = compare_capsule_formats(max_tasks=5, log_run=False, save_report=False)

    assert res["total_tasks_evaluated"] == 5
    assert "baseline_raw_full_files" in res
    assert "json_capsule" in res
    assert "compact_text_capsule" in res
    assert "comparison_summary" in res

    summary = res["comparison_summary"]
    assert summary["recommended_format"] == "compact_text"
    assert summary["text_vs_json_token_savings_pct"] > 0
    assert summary["task_success_delta"] >= 0.0

    eff_red_text = res["compact_text_capsule"]["effective_token_reduction"]
    assert eff_red_text > 0.85, f"redução de tokens esperada >0.85, obtido: {eff_red_text}"


def test_siga_context_tool_backward_and_forward_compatibility(tmp_path: Path):
    import subprocess

    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "ServicoBL.java").write_text("public class ServicoBL {}", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@e",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        check=True,
    )
    out = siga_context(
        symbols=["ServicoBL"],
        task="Testar integracao da tool com nova capsula",
        repo=tmp_path,
    )

    # Chaves legadas (Phase 05)
    assert out["task"] == "Testar integracao da tool com nova capsula"
    assert out["symbols"] == ["ServicoBL"]
    assert "files" in out
    assert "outlines" in out
    assert "capsule_text" in out
    assert out["token_estimate"] > 0

    # Chaves novas (Phase 09)
    assert "primary_symbols" in out
    assert "flow" in out
    assert "domain" in out
    assert "persistence" in out
    assert "views" in out
    assert "migrations" in out
    assert "snippets" in out
    assert "capsule_json" in out
    assert "compact_text" in out
