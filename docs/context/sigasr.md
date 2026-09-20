# sigasr — SIGA-SR (solicitações/requisições: web + núcleo)

> Biblioteca de contexto SIGA (docs/18 §4, G06 — gerada por `scripts/gen_context_docs.py`). Fonte de grounding: clone do SIGA em `../` @ `48610bd65046` — cada símbolo abaixo foi resolvido por `siga_locate` real e as contagens são medidas no HEAD.

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Tamanho medido:** 181 arquivos `.java`; 62 JSPs; 39 migrações/SQLs.

## Responsabilidade

Módulo **SIGA-SR (solicitações/requisições: web + núcleo)** do SIGA (mapeamento do `pom.xml` raiz e docs/00–05).

### Regra de negócio

- `sigasr/src/main/java/br/gov/jfrj/siga/sr/model/SrConfiguracaoBL.java` — símbolo `SrConfiguracaoBL` (resolvido por `siga_locate`).

### Controllers

- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/AcordoController.java` — símbolo `AcordoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/AssociacaoController.java` — símbolo `AssociacaoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/AtributoController.java` — símbolo `AtributoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/CompatibilidadeController.java` — símbolo `CompatibilidadeController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/ConhecimentoController.java` — símbolo `ConhecimentoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/CorporativoController.java` — símbolo `CorporativoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/DesignacaoController.java` — símbolo `DesignacaoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/DisponibilidadeController.java` — símbolo `DisponibilidadeController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/EquipeController.java` — símbolo `EquipeController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/ItemConfiguracaoController.java` — símbolo `ItemConfiguracaoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/PesquisaSatisfacaoController.java` — símbolo `PesquisaSatisfacaoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/PrincipalController.java` — símbolo `PrincipalController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/SelecaoController.java` — símbolo `SelecaoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/SolicitacaoController.java` — símbolo `SolicitacaoController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/SolicitacaoEmailController.java` — símbolo `SolicitacaoEmailController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/SrController.java` — símbolo `SrController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/TestesController.java` — símbolo `TestesController` (resolvido por `siga_locate`).
- `sigasr/src/main/java/br/gov/jfrj/siga/sr/vraptor/TipoAcaoController.java` — símbolo `TipoAcaoController` (resolvido por `siga_locate`).

## Como usar

- Para reverificar um símbolo citado: `python -c "from tools.siga_locate import siga_locate; print(siga_locate('<Simbolo>', repo='..'))"`;
- Página gerada deterministicamente: regenerar com `python -m scripts.gen_context_docs` após atualizar o clone.

## Provenance

- Gerada por G06 (docs/18 §4) a partir do clone real; verificação determinística via `tools/siga_locate.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença (`docs/14`). Sem parecer jurídico.
