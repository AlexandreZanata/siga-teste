"""Gerador de hard negatives para o SIGA Needle Expert (P06-T02, docs/07 §4 e docs/08 §2).

Subcategorias de hard negatives:
1. off-topic: perguntas fora do escopo do repositório SIGA (answers: [], tools: []).
2. similar-tool: queries que poderiam confundir a seleção de ferramentas (ex: history vs locate, impact vs trace).
3. similar-args: termos parecidos onde o argumento correto é estritamente específico (ex: ExDocumento vs ExDocumentoDTO).
4. homonym: mesmo nome base presente em diferentes camadas arquiteturais (entidade vs controller vs jsp vs DAO).
5. neighboring-module: distinção entre módulos irmãos do SIGA (siga-ex vs siga-sr, siga-cp, siga-wf, etc.).
6. ambiguous-incomplete: queries com informação insuficiente onde a ação correta é pedir esclarecimento ou recusar.
"""

from __future__ import annotations

from typing import Any

HARD_NEGATIVE_TEMPLATES: list[dict[str, Any]] = [
    # 1. Off-topic (perguntas gerais sem relação com SIGA -> sem chamada de tool)
    {
        "subcategory": "off-topic",
        "query": "Qual é a receita tradicional de pão de queijo mineiro?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "culinária -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Qual a distância aproximada em anos-luz até a galáxia de Andrômeda?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "astronomia -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Quem foi a seleção campeã da Copa do Mundo de futebol de 1970 no México?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "esportes -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Como trocar o pneu furado de um automóvel sedan com segurança?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "mecânica automotiva -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Qual é a capital da Austrália?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "geografia -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Como cultivar orquídeas phalaenopsis em vaso de cerâmica?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "botânica -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Explique a teoria da relatividade geral de Albert Einstein de modo simples.",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "física teórica -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Qual a previsão do tempo para a próxima semana em Belo Horizonte?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "meteorologia -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Quais ingredientes são necessários para fazer uma feijoada completa tradicional?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "culinária -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Como afinar um violão acústico padrão de seis cordas de ouvido?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "música -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Quantos planetas existem no sistema solar segundo a União Astronômica Internacional?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "astronomia -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },
    {
        "subcategory": "off-topic",
        "query": "Traduza o poema The Raven de Edgar Allan Poe para a língua francesa.",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "literatura/tradução -> fora do escopo do repositório SIGA (off-topic)",
        "final": "OFF_TOPIC",
    },

    # 2. Similar-tool (ferramenta semelhante: frases que poderiam induzir a tool errada)
    {
        "subcategory": "similar-tool",
        "query": "Mostrar o histórico Git de alterações recentes no arquivo ExDocumento.java",
        "expected_tools": ["siga_history"],
        "target": "ExDocumento.java",
        "expected_action": "call_history_not_locate",
        "reasoning": "ExDocumento.java -> target, histórico Git solicitado -> siga_history (não siga_locate)",
        "args": {"target": "ExDocumento.java", "limit": 5},
    },
    {
        "subcategory": "similar-tool",
        "query": "Qual foi o último commit e diff que alterou a classe ExTramiteBL?",
        "expected_tools": ["siga_history"],
        "target": "ExTramiteBL.java",
        "expected_action": "call_history_not_trace",
        "reasoning": "ExTramiteBL.java -> target, commit e diff solicitados -> siga_history (não siga_trace)",
        "args": {"target": "ExTramiteBL.java", "limit": 3},
    },
    {
        "subcategory": "similar-tool",
        "query": "Quais métodos chamadores e classes serão afetados se eu alterar ExBL?",
        "expected_tools": ["siga_impact"],
        "target": "ExBL",
        "expected_action": "call_impact_not_trace",
        "reasoning": "ExBL -> target, impacto em chamadores -> siga_impact (não siga_trace)",
        "args": {"target": "ExBL"},
    },
    {
        "subcategory": "similar-tool",
        "query": "Quem são todos os chamadores (callers estáticos) de ExDocumentoController?",
        "expected_tools": ["siga_impact"],
        "target": "ExDocumentoController",
        "expected_action": "call_impact_not_locate",
        "reasoning": "ExDocumentoController -> target, callers estáticos -> siga_impact (não siga_locate)",
        "args": {"target": "ExDocumentoController"},
    },
    {
        "subcategory": "similar-tool",
        "query": "Traçar o fluxo arquitetural de execução de ponta a ponta a partir de ExDocumentoController",
        "expected_tools": ["siga_trace"],
        "target": "ExDocumentoController",
        "expected_action": "call_trace_not_impact",
        "reasoning": "ExDocumentoController -> symbol, fluxo arquitetural de execução -> siga_trace (não siga_impact)",
        "args": {"symbol": "ExDocumentoController", "depth": 2},
    },
    {
        "subcategory": "similar-tool",
        "query": "Gerar uma cápsula de contexto compacta contendo ExDocumento e ExDocumentoController para refatoração",
        "expected_tools": ["siga_context"],
        "target": "ExDocumento",
        "expected_action": "call_context_not_locate",
        "reasoning": "ExDocumento, ExDocumentoController -> symbols, gerar cápsula de contexto -> siga_context (não siga_locate)",
        "args": {"symbols": ["ExDocumento", "ExDocumentoController"], "task": "Refatoração de documento"},
    },

    # 3. Similar-args (argumentos parecidos onde a precisão de nome é essencial)
    {
        "subcategory": "similar-args",
        "query": "Localizar especificamente a entidade JPA ExDocumento sem trazer classes DTO ou VO",
        "expected_tools": ["siga_locate"],
        "target": "ExDocumento",
        "expected_action": "exact_entity_name",
        "reasoning": "ExDocumento -> target, kind=entity -> siga_locate",
        "args": {"query": "ExDocumento", "kind": "entity"},
    },
    {
        "subcategory": "similar-args",
        "query": "Encontrar a página JSP marcar.jsp evitando confundir com marca.jsp",
        "expected_tools": ["siga_locate"],
        "target": "marcar.jsp",
        "expected_action": "exact_jsp_name",
        "reasoning": "marcar.jsp -> target, kind=jsp -> siga_locate",
        "args": {"query": "marcar.jsp", "kind": "jsp"},
    },
    {
        "subcategory": "similar-args",
        "query": "Buscar a página JSP exibe.jsp sem confundir com exibir.jsp",
        "expected_tools": ["siga_locate"],
        "target": "exibe.jsp",
        "expected_action": "exact_jsp_name",
        "reasoning": "exibe.jsp -> target, kind=jsp -> siga_locate",
        "args": {"query": "exibe.jsp", "kind": "jsp"},
    },
    {
        "subcategory": "similar-args",
        "query": "Localizar o arquivo de migração V104 referente a ExDocumento",
        "expected_tools": ["siga_locate"],
        "target": "siga.ex_documento",
        "expected_action": "exact_migration_target",
        "reasoning": "siga.ex_documento -> target, kind=migration -> siga_locate",
        "args": {"query": "siga.ex_documento", "kind": "migration"},
    },
    {
        "subcategory": "similar-args",
        "query": "Localizar a lógica de negócio ExTramiteBL sem confundir com ExMobilBL",
        "expected_tools": ["siga_locate"],
        "target": "ExTramiteBL",
        "expected_action": "exact_bl_symbol",
        "reasoning": "ExTramiteBL -> target, kind=symbol -> siga_locate",
        "args": {"query": "ExTramiteBL", "kind": "symbol"},
    },

    # 4. Homonym (homônimos: mesmo nome em camadas distintas)
    {
        "subcategory": "homonym",
        "query": "Localizar a entidade JPA ExModelo (tabela de modelos), não o controller",
        "expected_tools": ["siga_locate"],
        "target": "ExModelo",
        "expected_action": "discriminate_entity_layer",
        "reasoning": "ExModelo -> query, kind=entity -> siga_locate",
        "args": {"query": "ExModelo", "kind": "entity"},
    },
    {
        "subcategory": "homonym",
        "query": "Localizar o controlador VRaptor ExModeloController, não a entidade",
        "expected_tools": ["siga_locate"],
        "target": "ExModeloController",
        "expected_action": "discriminate_controller_layer",
        "reasoning": "ExModeloController -> query, kind=controller -> siga_locate",
        "args": {"query": "ExModeloController", "kind": "controller"},
    },
    {
        "subcategory": "homonym",
        "query": "Localizar o arquivo JSP de template modelo.jsp da camada de visualização",
        "expected_tools": ["siga_locate"],
        "target": "modelo.jsp",
        "expected_action": "discriminate_view_layer",
        "reasoning": "modelo.jsp -> query, kind=jsp -> siga_locate",
        "args": {"query": "modelo.jsp", "kind": "jsp"},
    },
    {
        "subcategory": "homonym",
        "query": "Localizar a entidade JPA ExClassificacao no pacote de modelo",
        "expected_tools": ["siga_locate"],
        "target": "ExClassificacao",
        "expected_action": "discriminate_entity_layer",
        "reasoning": "ExClassificacao -> query, kind=entity -> siga_locate",
        "args": {"query": "ExClassificacao", "kind": "entity"},
    },
    {
        "subcategory": "homonym",
        "query": "Localizar o controller ExClassificacaoController na camada web",
        "expected_tools": ["siga_locate"],
        "target": "ExClassificacaoController",
        "expected_action": "discriminate_controller_layer",
        "reasoning": "ExClassificacaoController -> query, kind=controller -> siga_locate",
        "args": {"query": "ExClassificacaoController", "kind": "controller"},
    },
    {
        "subcategory": "homonym",
        "query": "Localizar a entidade ExFormaDocumento referente a formas documentais",
        "expected_tools": ["siga_locate"],
        "target": "ExFormaDocumento",
        "expected_action": "discriminate_entity_layer",
        "reasoning": "ExFormaDocumento -> query, kind=entity -> siga_locate",
        "args": {"query": "ExFormaDocumento", "kind": "entity"},
    },
    {
        "subcategory": "homonym",
        "query": "Localizar o controller ExFormaDocumentoController no módulo web",
        "expected_tools": ["siga_locate"],
        "target": "ExFormaDocumentoController",
        "expected_action": "discriminate_controller_layer",
        "reasoning": "ExFormaDocumentoController -> query, kind=controller -> siga_locate",
        "args": {"query": "ExFormaDocumentoController", "kind": "controller"},
    },

    # 5. Neighboring-module (módulos vizinhos do ecossistema SIGA)
    {
        "subcategory": "neighboring-module",
        "query": "Identificar recursos do módulo siga-sr (serviços) sem misturar com expediente siga-ex",
        "expected_tools": ["siga_locate"],
        "target": "siga-sr",
        "expected_action": "discriminate_module_boundary",
        "reasoning": "siga-sr -> query, busca em módulo vizinho -> siga_locate",
        "args": {"query": "siga-sr", "kind": "file"},
    },
    {
        "subcategory": "neighboring-module",
        "query": "Localizar configurações corporativas do módulo siga-cp sem cruzar com siga-ex",
        "expected_tools": ["siga_locate"],
        "target": "siga-cp",
        "expected_action": "discriminate_module_boundary",
        "reasoning": "siga-cp -> query, busca em módulo vizinho -> siga_locate",
        "args": {"query": "siga-cp", "kind": "file"},
    },
    {
        "subcategory": "neighboring-module",
        "query": "Verificar definições de processos no módulo siga-wf sem contaminar siga-ex",
        "expected_tools": ["siga_locate"],
        "target": "siga-wf",
        "expected_action": "discriminate_module_boundary",
        "reasoning": "siga-wf -> query, busca em módulo vizinho -> siga_locate",
        "args": {"query": "siga-wf", "kind": "file"},
    },
    {
        "subcategory": "neighboring-module",
        "query": "Localizar arquivos de transporte e veículos do módulo siga-tp",
        "expected_tools": ["siga_locate"],
        "target": "siga-tp",
        "expected_action": "discriminate_module_boundary",
        "reasoning": "siga-tp -> query, busca em módulo vizinho -> siga_locate",
        "args": {"query": "siga-tp", "kind": "file"},
    },

    # 6. Ambiguous-incomplete (incompletas ou insuficientes: sem parâmetro essencial)
    {
        "subcategory": "ambiguous-incomplete",
        "query": "Corrigir o erro no método salvar da aplicação",
        "expected_tools": [],
        "expected_action": "clarification_needed",
        "reasoning": "vago -> classe/controller não informada (informação insuficiente)",
        "final": "CLARIFICATION_NEEDED",
    },
    {
        "subcategory": "ambiguous-incomplete",
        "query": "Ajustar a migração SQL do banco de dados",
        "expected_tools": [],
        "expected_action": "clarification_needed",
        "reasoning": "vago -> tabela/versão de migração não informada (informação insuficiente)",
        "final": "CLARIFICATION_NEEDED",
    },
    {
        "subcategory": "ambiguous-incomplete",
        "query": "Atualizar a estilização CSS da tela principal",
        "expected_tools": [],
        "expected_action": "clarification_needed",
        "reasoning": "vago -> tela/JSP não informada (informação insuficiente)",
        "final": "CLARIFICATION_NEEDED",
    },
    {
        "subcategory": "ambiguous-incomplete",
        "query": "Executar o teste que falhou no build de integração",
        "expected_tools": [],
        "expected_action": "clarification_needed",
        "reasoning": "vago -> nome do teste não informado (informação insuficiente)",
        "final": "CLARIFICATION_NEEDED",
    },
    {
        "subcategory": "ambiguous-incomplete",
        "query": "Adicionar validação de campo obrigatório na tela",
        "expected_tools": [],
        "expected_action": "clarification_needed",
        "reasoning": "vago -> entidade ou campo não informados (informação insuficiente)",
        "final": "CLARIFICATION_NEEDED",
    },
]


def generate_hard_negative_tasks(
    prefix: str = "task-hardneg",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Gera tarefas de hard negative categorizadas."""
    tasks = []
    templates = HARD_NEGATIVE_TEMPLATES if limit is None else HARD_NEGATIVE_TEMPLATES[:limit]

    for idx, tpl in enumerate(templates, 1):
        task = {
            "id": f"{prefix}-{idx:03d}",
            "category": "hard_negative",
            "subcategory": tpl["subcategory"],
            "query": tpl["query"],
            "expected_tools": tpl.get("expected_tools", []),
            "expected_action": tpl.get("expected_action", "evaluate"),
            "reasoning": tpl.get("reasoning", ""),
            "difficulty": "medium",
        }
        if "target" in tpl:
            task["target"] = tpl["target"]
        if "args" in tpl:
            task["args"] = tpl["args"]
        if "final" in tpl:
            task["final"] = tpl["final"]
        tasks.append(task)

    return tasks


def generate_off_topic_tasks(count: int = 15, prefix: str = "task-offtopic") -> list[dict[str, Any]]:
    """Gera conjunto parametrizável de tarefas puramente off-topic (answers: [], tools: [])."""
    off_topics = [t for t in HARD_NEGATIVE_TEMPLATES if t["subcategory"] == "off-topic"]
    results = []
    for idx in range(count):
        base = off_topics[idx % len(off_topics)]
        task_id = f"{prefix}-{idx + 1:03d}"
        suffix = f" (variação {idx // len(off_topics) + 1})" if idx >= len(off_topics) else ""
        results.append(
            {
                "id": task_id,
                "category": "hard_negative",
                "subcategory": "off-topic",
                "query": base["query"] + suffix,
                "expected_tools": [],
                "expected_action": "refusal",
                "reasoning": base["reasoning"],
                "final": "OFF_TOPIC",
                "difficulty": "easy",
            }
        )
    return results
