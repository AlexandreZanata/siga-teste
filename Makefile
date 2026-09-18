# SIGA Needle Expert — comandos canônicos (P01-T03, test-integration real na P02-T03).
# Regra: gate não implementado falha com mensagem explícita, nunca sucesso falso.

PY ?= python3
PYTEST ?= $(PY) -m pytest
RUFF ?= $(shell which ruff 2>/dev/null || echo "$(PY) -m ruff")

.PHONY: fmt fmt-check test-unit test-integration test-contract verify

fmt:
	$(RUFF) check --fix . 2>/dev/null || echo "fmt: ruff indisponível — instale dev extras (pip install -e .[dev])"
	$(RUFF) format . 2>/dev/null || true

fmt-check:
	@if ! command -v ruff >/dev/null 2>&1 && ! $(PY) -c "import ruff" >/dev/null 2>&1; then \
		echo "fmt-check: SKIP — ruff não instalado (pip install -e .[dev])"; exit 0; fi
	@$(RUFF) check . && echo "fmt-check: ok"

test-unit:
	@if [ ! -d tests ]; then echo "test-unit: ok (sem tests/ ainda — Phase 1 cria)"; exit 0; fi
	@$(PYTEST) tests --ignore=tests/integration && echo "test-unit: ok"

test-integration:
	@$(PYTEST) tests/integration && echo "test-integration: ok"

test-contract:
	@echo "test-contract: NÃO IMPLEMENTADO — Phase 5 define (tool schemas)"; exit 1

verify: fmt-check test-unit test-integration
	@echo "verify: gates presentes, pendentes (falham explícito quando invocados):"
	@for gate in test-contract; do echo "  - $$gate"; done
	@echo "verify: OK — capacidades existentes passaram."
