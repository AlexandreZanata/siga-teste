# sigawf — camada web do workflow (controllers + JSPs de procedimento)

> Biblioteca de contexto SIGA (docs/18 §4, G06 — gerada por `scripts/gen_context_docs.py`). Fonte de grounding: clone do SIGA em `../` @ `48610bd65046` — cada símbolo abaixo foi resolvido por `siga_locate` real e as contagens são medidas no HEAD.

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Tamanho medido:** 71 arquivos `.java`; 37 JSPs.

## Responsabilidade

Módulo **camada web do workflow (controllers + JSPs de procedimento)** do SIGA (mapeamento do `pom.xml` raiz e docs/00–05).

### Controllers

- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfAdminController.java` — símbolo `WfAdminController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfAppController.java` — símbolo `WfAppController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfConfiguracaoController.java` — símbolo `WfConfiguracaoController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfController.java` — símbolo `WfController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfDiagramaController.java` — símbolo `WfDiagramaController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfProcedimentoController.java` — símbolo `WfProcedimentoController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfRelatorioController.java` — símbolo `WfRelatorioController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfResponsavelController.java` — símbolo `WfResponsavelController` (resolvido por `siga_locate`).
- `sigawf/src/legacy/java/br/gov/jfrj/siga/wf/vraptor/WfSelecionavelController.java` — símbolo `WfSelecionavelController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringAdminController.java` — símbolo `WfSpringAdminController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringAppController.java` — símbolo `WfSpringAppController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringConfiguracaoController.java` — símbolo `WfSpringConfiguracaoController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringController.java` — símbolo `WfSpringController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringDiagramaController.java` — símbolo `WfSpringDiagramaController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringProcedimentoController.java` — símbolo `WfSpringProcedimentoController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringRelatorioController.java` — símbolo `WfSpringRelatorioController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringResponsavelController.java` — símbolo `WfSpringResponsavelController` (resolvido por `siga_locate`).
- `sigawf/src/main/java/br/gov/jfrj/siga/wf/spring/WfSpringSelecionavelController.java` — símbolo `WfSpringSelecionavelController` (resolvido por `siga_locate`).

## Como usar

- Para reverificar um símbolo citado: `python -c "from tools.siga_locate import siga_locate; print(siga_locate('<Simbolo>', repo='..'))"`;
- Página gerada deterministicamente: regenerar com `python -m scripts.gen_context_docs` após atualizar o clone.

## Provenance

- Gerada por G06 (docs/18 §4) a partir do clone real; verificação determinística via `tools/siga_locate.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença (`docs/14`). Sem parecer jurídico.
