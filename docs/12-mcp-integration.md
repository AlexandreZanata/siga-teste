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

## ADR-024 — Auth fail-closed + rate limit no servidor MCP antes de qualquer exposição (F14)

- **Decision:** toda requisição MCP carrega o token em `_siga_auth`; o servidor o valida com `hmac.compare_digest` contra o token de boot carregado de `SIGA_MCP_TOKEN_FILE` (preferido) ou `SIGA_MCP_TOKEN`. Sem nenhuma das duas variáveis o servidor não sobe e toda requisição é recusada com `-32001` (fail-closed). Rate limit sliding-window em memória por token (`SIGA_MCP_RATE_LIMIT`, padrão 60 req; `SIGA_MCP_RATE_WINDOW_SECONDS`, padrão 60s) responde `-32002`. `dispatch()` e o envelope de sucesso ficam intactos (ADR-020 preservado); `mcp/schema.json` documenta o mecanismo sem carregar segredo. Só stdlib (`hmac`, `collections`, `threading`) — determinístico primeiro.
- **Reason:** o NOT-build de `docs/15` §6 proíbe "MCP público sem auth"; `docs/12` §1 já desenhava auth local por token em arquivo. Transporte stdio é um cliente único local, mas qualquer exposição futura (rede/HTTP) exige que auth e contenção de volume já existam **antes**.
- **Alternatives:** auth na camada de transporte (TLS/OAuth) — antecipa chassi de rede fora do escopo V1 e não protege o stdio local; token em flag de linha de comando — vaza em `ps`/logs de shell.
- **Advantages:** recusa universal sem configuração; comparação em tempo constante; identidade do token reduzida a sha256 (segredo nunca retido nem ecoado em erros/provenance); janela deslizante sem dependências.
- **Disadvantages:** contador por processo (stdio = um cliente por processo, suficiente para V1); cliente de referência precisa da variável de ambiente no boot.
- **Risks:** token colado em logs — mitigado: o token só trafega por requisição e nunca é ecoado; `SIGA_MCP_TOKEN_FILE` ilegível falha o boot em vez de degradar para sem-auth.
- **Validate:** contract tests recusam requisição sem/par token com -32001, exceder a janela devolve -32002 e o caminho feliz dos 5 métodos permanece intacto com envelope inalterado.

## 2. Operação segura (F14)

1. Gere um token local (ex.: `openssl rand -hex 32`) e grave em arquivo com permissão restrita ao usuário; 2. aponte `SIGA_MCP_TOKEN_FILE` para esse arquivo (ou use `SIGA_MCP_TOKEN` com o valor literal); 3. opcionalmente ajuste `SIGA_MCP_RATE_LIMIT`/`SIGA_MCP_RATE_WINDOW_SECONDS`; 4. inicie o servidor normalmente (`python -m mcp.server`) — sem as variáveis ele falha no boot; 5. o cliente (OpenCode, Codex, Claude Code, Cursor ou `mcp/client.py`) envia o token por requisição; sem token configurado o cliente também não inicia. Modo offline total: nenhuma das etapas acessa rede.
