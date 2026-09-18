"""Catálogo sistemático de 500 tarefas para geração de dataset gold (P06-T02, docs/07 e docs/08).

Gera 500 tarefas diversificadas e grounded sobre o ecossistema SIGA:
- locate (~150): controllers, entidades, lógica de negócio, jsp, migrações, testes, arquivos
- trace (~75): rastreamento de fluxos arquiteturais de execução (depth 1, 2, 3)
- impact (~75): análise de impacto estático (callers, callees, dependências)
- history (~60): histórico Git, diffs, co-alterações (CHANGED_WITH)
- hard_negatives (~140):
  * off-topic (~60, recusa/answers: [])
  * similar-tool (~20, discriminação de ferramentas)
  * similar-args (~20, precisão de parâmetros)
  * homonym (~20, desambiguação de camadas)
  * neighboring-module (~10, limites modulares)
  * ambiguous-incomplete (~10, informação insuficiente)
"""

from __future__ import annotations

from typing import Any

from task_factory.hard_negatives import HARD_NEGATIVE_TEMPLATES

# Lista canônica de símbolos e componentes reais do SIGA
CORE_ENTITIES = [
    "ExDocumento",
    "ExMobil",
    "ExModelo",
    "ExFormaDocumento",
    "ExClassificacao",
    "ExVia",
    "ExTipoDocumento",
    "ExMovimentacao",
    "ExPreenchimento",
    "ExPapel",
    "ExNivelAcesso",
    "ExEstadoDoc",
    "ExMarca",
    "ExEmailNotificacao",
    "ExBoletimDoc",
]

CORE_CONTROLLERS = [
    "ExDocumentoController",
    "ExMovimentacaoController",
    "ExMobilController",
    "ExModeloController",
    "ExClassificacaoController",
    "ExFormaDocumentoController",
    "ExRelatorioController",
]

CORE_BLS = [
    "ExBL",
    "ExTramiteBL",
    "ExConfiguracaoBL",
    "ExMarcadorBL",
    "ExCompetenciaBL",
]

CORE_JSPS = [
    "exibe.jsp",
    "marcar.jsp",
    "edita.jsp",
    "lista.jsp",
    "protocolo.jsp",
    "anexa.jsp",
    "aAssinar.jsp",
    "aAnotar.jsp",
]

CORE_MIGRATIONS = [
    "siga.ex_documento",
    "siga.ex_mobil",
    "siga.ex_modelo",
    "siga.ex_classificacao",
    "siga.ex_movimentacao",
    "siga.ex_forma_documento",
    "siga.ex_via",
]

CORE_TESTS = [
    "ExTramiteBLTest",
    "ExBLTest",
    "ExDocumentoTest",
    "ExMobilTest",
    "ExModeloTest",
    "ExClassificacaoTest",
]


def build_task_catalog() -> list[dict[str, Any]]:
    """Gera o catálogo completo de 500 tarefas."""
    tasks: list[dict[str, Any]] = []
    task_num = 1

    # -------------------------------------------------------------
    # 1. LOCATE (150 tarefas)
    # -------------------------------------------------------------
    # 1.1 Controllers
    for ctrl in CORE_CONTROLLERS:
        for phrasing in [
            f"Localizar o controller {ctrl} responsável pelo fluxo web",
            f"Onde está definido o controller {ctrl} no módulo sigaex?",
            f"Encontrar arquivo de controle {ctrl}.java",
        ]:
            tasks.append({
                "id": f"task-cat-{task_num:04d}",
                "category": "locate",
                "subcategory": "controller",
                "target": ctrl,
                "query": phrasing,
                "expected_tools": ["siga_locate"],
                "args": {"query": ctrl, "kind": "controller"},
                "difficulty": "easy",
            })
            task_num += 1

    # 1.2 Entidades
    for ent in CORE_ENTITIES:
        for phrasing in [
            f"Localizar a entidade JPA {ent} do modelo de dados de expediente",
            f"Encontrar mapeamento da classe de entidade {ent}",
        ]:
            tasks.append({
                "id": f"task-cat-{task_num:04d}",
                "category": "locate",
                "subcategory": "entity",
                "target": ent,
                "query": phrasing,
                "expected_tools": ["siga_locate"],
                "args": {"query": ent, "kind": "entity"},
                "difficulty": "easy",
            })
            task_num += 1

    # 1.3 Lógica de Negócio (BL / Símbolos)
    for bl in CORE_BLS:
        for phrasing in [
            f"Onde fica a classe de lógica de negócio {bl}?",
            f"Localizar regras de negócio implementadas em {bl}",
            f"Encontrar a classe {bl} no módulo siga-ex",
        ]:
            tasks.append({
                "id": f"task-cat-{task_num:04d}",
                "category": "locate",
                "subcategory": "symbol",
                "target": bl,
                "query": phrasing,
                "expected_tools": ["siga_locate"],
                "args": {"query": bl, "kind": "symbol"},
                "difficulty": "easy",
            })
            task_num += 1

    # 1.4 JSPs
    for jsp in CORE_JSPS:
        for phrasing in [
            f"Buscar página de exibição {jsp} no sigaex",
            f"Localizar arquivo JSP {jsp} de interface web",
        ]:
            tasks.append({
                "id": f"task-cat-{task_num:04d}",
                "category": "locate",
                "subcategory": "jsp",
                "target": jsp,
                "query": phrasing,
                "expected_tools": ["siga_locate"],
                "args": {"query": jsp, "kind": "jsp"},
                "difficulty": "easy",
            })
            task_num += 1

    # 1.5 Migrações
    for mig in CORE_MIGRATIONS:
        for phrasing in [
            f"Localizar migração de banco de dados para a tabela {mig}",
            f"Buscar script SQL Flyway da tabela {mig}",
        ]:
            tasks.append({
                "id": f"task-cat-{task_num:04d}",
                "category": "locate",
                "subcategory": "migration",
                "target": mig,
                "query": phrasing,
                "expected_tools": ["siga_locate"],
                "args": {"query": mig, "kind": "migration"},
                "difficulty": "medium",
            })
            task_num += 1

    # 1.6 Testes
    for tst in CORE_TESTS:
        for phrasing in [
            f"Localizar testes unitários de {tst}",
            f"Onde estão os testes automatizados da classe {tst}?",
        ]:
            tasks.append({
                "id": f"task-cat-{task_num:04d}",
                "category": "locate",
                "subcategory": "test",
                "target": tst,
                "query": phrasing,
                "expected_tools": ["siga_locate"],
                "args": {"query": tst, "kind": "test"},
                "difficulty": "easy",
            })
            task_num += 1

    # Ajusta total de locate para exatamente 150 se necessário
    while len([t for t in tasks if t["category"] == "locate"]) < 150:
        idx = len([t for t in tasks if t["category"] == "locate"]) % len(CORE_ENTITIES)
        ent = CORE_ENTITIES[idx]
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "locate",
            "subcategory": "file",
            "target": f"{ent}.java",
            "query": f"Localizar código fonte do arquivo {ent}.java no repositório",
            "expected_tools": ["siga_locate"],
            "args": {"query": f"{ent}.java", "kind": "file"},
            "difficulty": "easy",
        })
        task_num += 1

    # Se passou de 150, corta locate
    locate_tasks = [t for t in tasks if t["category"] == "locate"][:150]
    tasks = locate_tasks

    # -------------------------------------------------------------
    # 2. TRACE (75 tarefas)
    # -------------------------------------------------------------
    trace_sources = CORE_CONTROLLERS + CORE_BLS + CORE_ENTITIES[:5]
    for idx in range(75):
        sym = trace_sources[idx % len(trace_sources)]
        depth = 1 if idx % 3 == 0 else 2
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "trace",
            "subcategory": "architectural-flow",
            "target": sym,
            "query": f"Traçar o fluxo arquitetural de execução a partir de {sym} com profundidade {depth}",
            "expected_tools": ["siga_trace"],
            "args": {"symbol": sym, "depth": depth},
            "difficulty": "medium" if depth == 1 else "hard",
        })
        task_num += 1

    # -------------------------------------------------------------
    # 3. IMPACT (75 tarefas)
    # -------------------------------------------------------------
    impact_sources = CORE_BLS + CORE_CONTROLLERS + CORE_ENTITIES[:5]
    for idx in range(75):
        sym = impact_sources[idx % len(impact_sources)]
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "impact",
            "subcategory": "callers-dependencies",
            "target": sym,
            "query": f"Analisar o impacto estático, chamadores e testes dependentes da classe {sym}",
            "expected_tools": ["siga_impact"],
            "args": {"target": sym},
            "difficulty": "medium",
        })
        task_num += 1

    # -------------------------------------------------------------
    # 4. HISTORY (60 tarefas)
    # -------------------------------------------------------------
    history_files = [f"{e}.java" for e in CORE_ENTITIES] + [f"{c}.java" for c in CORE_CONTROLLERS] + CORE_JSPS
    for idx in range(60):
        hf = history_files[idx % len(history_files)]
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "history",
            "subcategory": "git-history",
            "target": hf,
            "query": f"Verificar histórico de commits e co-alterações recentes do arquivo {hf}",
            "expected_tools": ["siga_history"],
            "args": {"target": hf, "limit": 5},
            "difficulty": "easy",
        })
        task_num += 1

    # -------------------------------------------------------------
    # 5. HARD NEGATIVES (140 tarefas)
    # -------------------------------------------------------------
    # 5.1 Off-topic (60 tarefas, answers: [], tools: [])
    off_topics = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "off-topic"]
    for idx in range(60):
        tpl = off_topics[idx % len(off_topics)]
        suffix = f" (amostra {idx // len(off_topics) + 1})" if idx >= len(off_topics) else ""
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "hard_negative",
            "subcategory": "off-topic",
            "query": tpl["query"] + suffix,
            "expected_tools": [],
            "expected_action": "refusal",
            "reasoning": tpl["reasoning"],
            "final": "OFF_TOPIC",
            "difficulty": "easy",
        })
        task_num += 1

    # 5.2 Similar-tool (20 tarefas)
    sim_tools = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "similar-tool"]
    for idx in range(20):
        tpl = sim_tools[idx % len(sim_tools)]
        suffix = f" (variação {idx // len(sim_tools) + 1})" if idx >= len(sim_tools) else ""
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "hard_negative",
            "subcategory": "similar-tool",
            "target": tpl.get("target"),
            "query": tpl["query"] + suffix,
            "expected_tools": tpl.get("expected_tools", []),
            "args": tpl.get("args", {}),
            "expected_action": tpl.get("expected_action"),
            "reasoning": tpl.get("reasoning"),
            "difficulty": "medium",
        })
        task_num += 1

    # 5.3 Similar-args (20 tarefas)
    sim_args = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "similar-args"]
    for idx in range(20):
        tpl = sim_args[idx % len(sim_args)]
        suffix = f" (variação {idx // len(sim_args) + 1})" if idx >= len(sim_args) else ""
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "hard_negative",
            "subcategory": "similar-args",
            "target": tpl.get("target"),
            "query": tpl["query"] + suffix,
            "expected_tools": tpl.get("expected_tools", []),
            "args": tpl.get("args", {}),
            "expected_action": tpl.get("expected_action"),
            "reasoning": tpl.get("reasoning"),
            "difficulty": "medium",
        })
        task_num += 1

    # 5.4 Homonym (20 tarefas)
    homonyms = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "homonym"]
    for idx in range(20):
        tpl = homonyms[idx % len(homonyms)]
        suffix = f" (variação {idx // len(homonyms) + 1})" if idx >= len(homonyms) else ""
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "hard_negative",
            "subcategory": "homonym",
            "target": tpl.get("target"),
            "query": tpl["query"] + suffix,
            "expected_tools": tpl.get("expected_tools", []),
            "args": tpl.get("args", {}),
            "expected_action": tpl.get("expected_action"),
            "reasoning": tpl.get("reasoning"),
            "difficulty": "medium",
        })
        task_num += 1

    # 5.5 Neighboring-module (10 tarefas)
    modules = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "neighboring-module"]
    for idx in range(10):
        tpl = modules[idx % len(modules)]
        suffix = f" (variação {idx // len(modules) + 1})" if idx >= len(modules) else ""
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "hard_negative",
            "subcategory": "neighboring-module",
            "target": tpl.get("target"),
            "query": tpl["query"] + suffix,
            "expected_tools": tpl.get("expected_tools", []),
            "args": tpl.get("args", {}),
            "expected_action": tpl.get("expected_action"),
            "reasoning": tpl.get("reasoning"),
            "difficulty": "medium",
        })
        task_num += 1

    # 5.6 Ambiguous-incomplete (10 tarefas)
    incompletes = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "ambiguous-incomplete"]
    for idx in range(10):
        tpl = incompletes[idx % len(incompletes)]
        suffix = f" (amostra {idx // len(incompletes) + 1})" if idx >= len(incompletes) else ""
        tasks.append({
            "id": f"task-cat-{task_num:04d}",
            "category": "hard_negative",
            "subcategory": "ambiguous-incomplete",
            "query": tpl["query"] + suffix,
            "expected_tools": [],
            "expected_action": "clarification_needed",
            "reasoning": tpl["reasoning"],
            "final": "CLARIFICATION_NEEDED",
            "difficulty": "easy",
        })
        task_num += 1

    return tasks
