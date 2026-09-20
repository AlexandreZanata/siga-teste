# sigagc — gestão de contratos (web + integração)

> Biblioteca de contexto SIGA (docs/18 §4, G06 — gerada por `scripts/gen_context_docs.py`). Fonte de grounding: clone do SIGA em `../` @ `48610bd65046` — cada símbolo abaixo foi resolvido por `siga_locate` real e as contagens são medidas no HEAD.

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Tamanho medido:** 45 arquivos `.java`; 28 JSPs; 12 migrações/SQLs.

## Responsabilidade

Módulo **gestão de contratos (web + integração)** do SIGA (mapeamento do `pom.xml` raiz e docs/00–05).

### Regra de negócio

- `sigagc/src/main/java/br/gov/jfrj/siga/gc/util/GcBL.java` — símbolo `GcBL` (resolvido por `siga_locate`).

### Controllers

- `sigagc/src/main/java/br/gov/jfrj/siga/gc/vraptor/AppController.java` — símbolo `AppController` (resolvido por `siga_locate`).
- `sigagc/src/main/java/br/gov/jfrj/siga/gc/vraptor/GcController.java` — símbolo `GcController` (resolvido por `siga_locate`).

### Serviços

- `sigagc/src/main/java/br/gov/jfrj/siga/gc/service/impl/GcServiceImpl.java` — símbolo `GcServiceImpl` (resolvido por `siga_locate`).

## Como usar

- Para reverificar um símbolo citado: `python -c "from tools.siga_locate import siga_locate; print(siga_locate('<Simbolo>', repo='..'))"`;
- Página gerada deterministicamente: regenerar com `python -m scripts.gen_context_docs` após atualizar o clone.

## Provenance

- Gerada por G06 (docs/18 §4) a partir do clone real; verificação determinística via `tools/siga_locate.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença (`docs/14`). Sem parecer jurídico.
