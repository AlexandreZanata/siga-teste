# 20 — Ramificação: MCP treinável para qualquer projeto (sem API key)

> Generalização do MCP SIGA (`docs/12`, `docs/18`, `docs/19`). Premissa herdada: treino por agente em IDE, custo ~zero, verifier determinístico como ground truth.

## 1. Ideia em uma frase

O mesmo chassi — indexer determinístico + 5 tools + bench congelado + factory agentiva + LoRA local — instancia um "especialista de repositório" para **qualquer projeto**, com um adaptador fino por projeto sobre uma base compartilhada.

## 2. O que é genérico vs. específico

- **Genérico (base única):** transporte MCP stdio + auth/rate (F14), envelope `{result, provenance, cost}`, bench temporal + splits, harness de scoring A/B, LoRA/CPU pipeline, protocolo de rodada cega multi-IDE (`docs/18`).
- **Específico (perfil por projeto):** `projeto.yaml` — linguagens Tree-sitter, globs de código/teste/migração, comando de teste, estratégia de símbolos (ex.: `ExBL` no SIGA ↔ `*Service` em outro), seeds do bench. Indexer lê o perfil; nada do SIGA vaza para outros projetos.

## 3. Treino sem API key (o método validado no G03)

1. Congelar bench do projeto (commits reais → tarefas, GT determinístico).
2. Rodadas cegas em IDEs de agente (braço A sem MCP vs B com MCP), operador que nunca viu o GT — exatamente o `PROTOCOL.md` da suite.
3. Verificação determinística promove respostas a gold; expansão com error analysis (padrão F06/ADR-017).
4. LoRA por projeto sobre a base, curvas medidas, compressão, GO com números.
5. Custo: máquina local + tempo de operador; zero chamada paga. O que se paga é disciplina, não token.

## 4. Gates por projeto (não herda o GO do SIGA)

Cada projeto instancia seu bench e precisa do próprio veredito `mcp_helps` (`task_success_delta > 0` com redução de tokens) antes de qualquer alegação. Contaminação entre projetos (treinar A com dados de B) segue a mesma regra do bench: prefixo isolado + verificação SHA.

## 5. DoD da ramificação

Chassi extraído sem imports do SIGA (`core` genérico + `profiles/`), um segundo projeto-piloto com bench próprio e veredito publicado, `make verify` verde nos dois, ADR registrando o que mudou na generalização. Licença por projeto documentada (AGPL do SIGA não contamina o chassi se nenhum código/dado dele for copiado — só o método).
