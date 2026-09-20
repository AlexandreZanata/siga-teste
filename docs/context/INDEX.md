# Biblioteca de contexto SIGA — índice

> Biblioteca de contexto para devs e IAs (docs/18 §4, G05). Cada página é
> gerada/validada contra o clone real do SIGA — **nenhum path ou símbolo
> inventado**: existência no HEAD e resolução por `siga_locate`/`siga_trace`
> (tools determinísticas deste repo).

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Regra:** página desatualizada = recalcular contra o HEAD atual e
  atualizar o `source_commit` acima; disparidade entre páginas é sempre
  detectável por este campo.

## Páginas

| Módulo | Papel | Página | Tamanho medido |
|---|---|---|---|
| `siga-ex` | core de negócio documental (entidades, BL, logic, DAO) | [siga-ex.md](siga-ex.md) | 501 `.java`, 0 JSPs |
| `sigaex` | camada web (controllers VRaptor/Spring + JSPs) | [sigaex.md](sigaex.md) | 237 `.java`, 597 JSPs |

## Cobertura

- **2 de ~25 módulos Maven** (`pom.xml` raiz) — lote 1 (núcleo) do docs/18 §4;
- Próximos lotes: G06 (docs/18 §5), em lotes de 2–3 módulos por tarefa;
- Convenção de nome: `docs/context/<modulo>.md`.

## Como usar

- Dev/IA chegando num domínio: começar pela página do módulo; `siga_locate`
  para achar símbolos citados; `siga_trace` para o fluxo;
- Agente com MCP: `siga_context` pode servir estas páginas como contexto
  (integração prevista no G06).

## Licença

Conteúdo derivado de código AGPLv3 (SIGA) — herda as obrigações da licença
(`docs/14`). Sem parecer jurídico.
