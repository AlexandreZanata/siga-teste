# Diretrizes para Agentes — SIGA Needle Expert

Regras mandatórias para qualquer IA ou desenvolvedor atuando neste repositório (`siga-teste`).
Nunca alterar o clone do SIGA em `../` — ele é somente leitura (branch `desenvolvimento`).

## 1. Regras de execução e Git

- **Uma microtarefa por vez:** execute exatamente uma tarefa `PXX-TYY` por ciclo. Proibido acumular, pular etapas ou ampliar escopo.
- **Base:** trabalhar somente em `siga-teste`. Nunca editar, mover ou commitar nada fora dele. `git status` no repo pai (`../`) deve continuar sem modificações rastreadas (apenas `siga-teste/` untracked é esperado).
- **Commits locais e atômicos:** cada tarefa concluída gera exatamente um commit local atômico após todos os gates passarem, dentro de `siga-teste`.
- **Padrão de commit:** Conventional Commits (`type(scope): descrição`), mensagem exata definida na tarefa.
- **Proibição de push/publicação:** nunca executar `git push`, criar PR, tag ou release sem autorização humana explícita. Publicação remota é decisão humana.
- **Proibição de operações destrutivas:** proibido `git reset --hard`, `git clean -fd`, `--force`, `--no-verify`.
- **Limpeza:** antes de alterar, confirmar `git status --short` limpo dentro de `siga-teste`. Ao final, limpo.
- **Segredos:** proibido commitar tokens, credenciais, emails pessoais, dumps de produção ou código proprietário fora do SIGA público.
- **Interrupção:** se qualquer validação falhar ou houver dúvida de requisito, parar sem commit e registrar bloqueio em `.local/PROGRESS.md`.

## 2. Arquitetura obrigatória (V1)

- **Estilo:** monólito Python simples + SQLite/DuckDB + CLI/API local. Sem microservices/K8s sem ADR.
- **Separação:** `pesos` (Needle) ≠ `graph` (fatos) ≠ `retrieval` (código atual). Novo commit no SIGA = `git pull` + reindex incremental, não retreino.
- **Determinístico primeiro:** tudo que AST/grep/Git/compilador/teste resolve sem LLM deve ser determinístico. LLM só onde há ganho medido.
- **Grounding de argumentos:** nunca inventar path/símbolo. Fluxo `task → locate(query da tarefa) → candidatos reais → trace(symbol real) → context(...)`.
- **Provenance:** todo registro de dataset preserva `repo_commit`, fonte, teacher, prompt version, timestamp, verifier, licença.
- **Licença:** SIGA é AGPLv3. Datasets/checkpoints/índices derivados herdam obrigações — documentar, nunca dar parecer jurídico definitivo.

## 3. Dependências

- **Standard-first:** Python stdlib + SQLite + Git + ripgrep antes de adicionar lib.
- **V1 permitidas (fixadas quando adicionadas):** `tree-sitter`/`tree-sitter-java` ou `javalang`/`JavaParser` (decidir em Phase 2 com ADR), `duckdb` ou `sqlite3` stdlib, `pytest`, `ruff` ou `black`.
- **Novas dependências:** exigem justificativa, avaliação de alternativa nativa e registro em `docs/DECISIONS.md` (ADR resumido). Proibido adicionar sem autorização da tarefa.
- **Needle/Cactus:** SDK/engine somente via adapter isolado (`inference/`). Versão fixada e documentada em Phase 6.

## 4. Validação e gates

Antes de qualquer commit, dentro de `siga-teste`:

```bash
git status --short --branch
git diff --check
git status --short
make fmt-check
make test-unit
```

Quando `Makefile` ganhar gates (`test-integration`, `test-contract`, `verify`), executar os pertinentes. Gate inexistente falha explícito, nunca sucesso falso.

- Python: `ruff check` (ou `black --check`) + `pytest -q`.
- Medições do SIGA: somente scripts read-only em `scripts/` (ex.: contar arquivos, mapear `pom.xml`). Nunca escrever em `../`.
- Benchmark/dataset nunca contaminados: splits temporais Git, holdout isolado em `datasets/benchmark/`.

## 5. Plano operacional

- Ler `.local/README.md`, `.local/MASTER_PLAN.md`, `.local/PROGRESS.md` (próxima tarefa), abrir somente a fase atual em `.local/phases/`.
- `.local/` é ignorado pelo Git (`*`). Nunca `git add -f .local/`.
- Registrar em `.local/PROGRESS.md`: ID, hash curto, data, comandos e resultado. Sem commit seguinte no mesmo turno.
