# 12 — MCP/API integration: Expert usável por agentes externos

> Cápsula como contrato em `docs/04` ADR-008; tools em `docs/06`. Decisões em ADR resumido.

## ADR-020 — MCP server fino sobre a cápsula, core desacoplado

- **Decision:** expor o Expert via MCP server (`mcp/server.py`) com 5 métodos espelhando as tools (`siga.locate/trace/impact/history/context`); OpenCode, Codex, Claude Code, Cursor e outros agentes MCP como clientes; core nunca importa código de cliente.
- **Reason:** ADR-008 já isola a IA grande via cápsula; MCP é só o transporte desse contrato. OpenCode é cliente, não arquitetura.
- **Alternatives:** API REST própria; acoplamento ao OpenCode.
- **Advantages:** qualquer agente compatível usa o especialista sem conhecer Needle/graph; medição dos 3 braços reutilizável.
- **Disadvantages:** overhead de protocolo; versionamento de schema MCP.
- **Risks:** cliente pedir busca livre fora da cápsula (negar: só os 5 métodos).
- **Validate:** P10 demonstra tarefa do slice resolvida via cliente MCP externo; `test-contract` do schema.

## 1. Contratos (P10 implementa; aqui o desenho)

Cada método recebe `{task, ...args grounding-safe}` e devolve `{capsule|results, provenance{index_version, repo_commit}, cost{tokens, latency}}`. Sem streaming de código bruto; snippets só dentro da cápsula mínima. Auth local por token em arquivo (sem rede externa obrigatória); modo offline total documentado.
