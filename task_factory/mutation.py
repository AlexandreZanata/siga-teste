"""Gerador de tarefas de mutação sintética (P06-T01, docs/08 §2).

Simula mutações de código para tarefas de localização e reparo de defeitos:
- condição invertida
- validação removida
- enum/annotation/import trocados
- SQL/JSP/endpoint quebrados
"""

from __future__ import annotations

from typing import Any

MUTATION_TEMPLATES: list[dict[str, Any]] = [
    {
        "mutation_type": "inverted_condition",
        "target_file": "ExTramiteBL.java",
        "target_symbol": "ExTramiteBL",
        "query": "Bug: tramitação está sendo bloqueada indevidamente para usuários com permissão ativa (condição invertida)",
        "mutation_diff": "- if (usuario.isAtivo())\n+ if (!usuario.isAtivo())",
        "expected_fix": "Restaurar checagem positiva da atividade do usuário",
    },
    {
        "mutation_type": "removed_validation",
        "target_file": "ExDocumentoController.java",
        "target_symbol": "ExDocumentoController",
        "query": "Falha de validação: salvamento de documento aceita título nulo sem validação prévia",
        "mutation_diff": "- if (doc.getDescrDocumento() == null) throw new ValidacaoException();",
        "expected_fix": "Adicionar novamente validação de nulidade na descrição do documento",
    },
    {
        "mutation_type": "swapped_annotation",
        "target_file": "ExDocumento.java",
        "target_symbol": "ExDocumento",
        "query": "Erro de persistência JPA: entidade não é reconhecida pelo EntityManager após troca acidental de anotação",
        "mutation_diff": "- @Entity\n+ @MappedSuperclass",
        "expected_fix": "Substituir anotação @MappedSuperclass por @Entity",
    },
    {
        "mutation_type": "swapped_import",
        "target_file": "ExMobil.java",
        "target_symbol": "ExMobil",
        "query": "Erro de compilação em ExMobil: tipo List importado de pacote incorreto",
        "mutation_diff": "- import java.util.List;\n+ import java.awt.List;",
        "expected_fix": "Corrigir importação para java.util.List",
    },
    {
        "mutation_type": "broken_sql_migration",
        "target_file": "SIGA_UTF8_V104__Documento_com_Principal.sql",
        "target_symbol": "siga.ex_documento",
        "query": "Falha na execução de migração Flyway: nome de coluna inexistente na instrução DDL",
        "mutation_diff": "- ID_DOC NUMBER(19)\n+ ID_DOC_ERR NUMBER(19)",
        "expected_fix": "Corrigir identificador da coluna ID_DOC no script SQL",
    },
    {
        "mutation_type": "broken_jsp_endpoint",
        "target_file": "exibe.jsp",
        "target_symbol": "exibe.jsp",
        "query": "Erro 404 ao submeter formulário em exibe.jsp: endpoint da ação do formulário foi corrompido",
        "mutation_diff": "- action=\"exDocumento/gravar\"\n+ action=\"exDocumento/gravar_invalido\"",
        "expected_fix": "Corrigir URL da action no JSP",
    },
]


def generate_mutation_tasks(prefix: str = "task-mut") -> list[dict[str, Any]]:
    """Gera lista canônica de tarefas com mutações sintéticas."""
    tasks = []
    for idx, tpl in enumerate(MUTATION_TEMPLATES, 1):
        tasks.append(
            {
                "id": f"{prefix}-{idx:03d}",
                "category": "mutation",
                "mutation_type": tpl["mutation_type"],
                "target_file": tpl["target_file"],
                "target_symbol": tpl["target_symbol"],
                "query": tpl["query"],
                "mutation_diff": tpl["mutation_diff"],
                "expected_fix": tpl["expected_fix"],
                "difficulty": "hard",
            }
        )
    return tasks
