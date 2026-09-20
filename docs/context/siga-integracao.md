# siga-integracao — integrações externas do expediente (serviços e clients)

> Biblioteca de contexto SIGA (docs/18 §4, G06 — gerada por `scripts/gen_context_docs.py`). Fonte de grounding: clone do SIGA em `../` @ `48610bd65046` — cada símbolo abaixo foi resolvido por `siga_locate` real e as contagens são medidas no HEAD.

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Tamanho medido:** 123 arquivos `.java`.

## Responsabilidade

Módulo **integrações externas do expediente (serviços e clients)** do SIGA (mapeamento do `pom.xml` raiz e docs/00–05).

### Serviços

- `siga-integracao/src/main/java/br/gov/jfrj/siga/integracao/ws/pubnet/service/PubnetCancelamentoService.java` — símbolo `PubnetCancelamentoService` (resolvido por `siga_locate`).
- `siga-integracao/src/main/java/br/gov/jfrj/siga/integracao/ws/pubnet/service/PubnetConsultaService.java` — símbolo `PubnetConsultaService` (resolvido por `siga_locate`).
- `siga-integracao/src/main/java/br/gov/jfrj/siga/integracao/ws/pubnet/service/PubnetEnvioService.java` — símbolo `PubnetEnvioService` (resolvido por `siga_locate`).

## Como usar

- Para reverificar um símbolo citado: `python -c "from tools.siga_locate import siga_locate; print(siga_locate('<Simbolo>', repo='..'))"`;
- Página gerada deterministicamente: regenerar com `python -m scripts.gen_context_docs` após atualizar o clone.

## Provenance

- Gerada por G06 (docs/18 §4) a partir do clone real; verificação determinística via `tools/siga_locate.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença (`docs/14`). Sem parecer jurídico.
