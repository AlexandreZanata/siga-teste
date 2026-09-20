# sigaex — módulo web do documento eletrônico

> Biblioteca de contexto SIGA (docs/18 §4, G05). Fonte de grounding:
> clone do SIGA em `../` @ `48610bd65046` — paths conferidos por existência
> no HEAD; símbolos resolvidos por `siga_locate`/`siga_trace` real. Para
> reverificar:
> `python -c "from tools.siga_locate import siga_locate; print(siga_locate('ExDocumentoController', repo='..'))"`.

- **source_commit (SIGA):** `48610bd65046`
- **Tamanho medido:** 237 arquivos `.java` + 597 JSPs em
  `sigaex/src/main/webapp/`.

## Responsabilidade

Camada **web** do documento eletrônico: controllers (VRaptor legado +
Spring novo) e as 597 páginas JSP. Consome o core via módulo `siga-ex`
(`ExBL`, entidades) — não implementa regra de negócio própria relevante.

## Entry points (arquivos reais no HEAD)

- **Controllers Spring (novo):** `sigaex/src/main/java/br/gov/jfrj/siga/ex/spring/ExSpringDocumentoController.java`
  e `sigaex/src/main/java/br/gov/jfrj/siga/ex/spring/ExSpringMesa2Controller.java`
  (diretório com 26 controllers).
- **Controllers VRaptor (legado):** `sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java`
  e `sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExController.java`
  (diretório com 27 controllers); **fonte Java em `src/legacy/java`**, não em
  `src/main/java`.
- **JSPs:** `sigaex/src/main/webapp/WEB-INF/page/exDocumento/edita.jsp` —
  páginas organizadas por domínio em
  `sigaex/src/main/webapp/WEB-INF/page/` (ex.: `exDocumento/`,
  `exMovimentacao/`).

## Como adicionar feature / corrigir bug

1. Endpoint novo → controller Spring em `.../ex/spring/` (padrão preferido
   para código novo); manutencão de tela legada → VRaptor em `src/legacy/`;
2. Tela → JSP em `src/main/webapp/WEB-INF/page/<dominio>/`; mudanças de
   navegação/ação costumam envolver controller + JSP emparelhados;
3. Regra de negócio → **não** escrever aqui: descer para `siga-ex`
   (`ExBL`/`logic/*`) e chamar do controller;
4. Permissão de acesso a ação → `ExCompetenciaBL` (no core), não no
   controller.

## Armadilhas (grounded)

- **Dois frameworks de controller convivendo**: VRaptor (`src/legacy/java`)
  e Spring (`src/main/java/.../spring/`) — o mesmo domínio pode ter
  `ExDocumentoController` (legacy) **e** `ExSpringDocumentoController`
  (novo); procurar só um dos padrões dá meia resposta;
- **`src/legacy/java`**: buscas que assumem `src/main/java` perdem os 27
  controllers legados (ex.:
  `sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExClassificacaoController.java`);
- **597 JSPs**: páginas não estão em classes — localização por texto do
  rótulo/fluxo costuma mirar `WEB-INF/page/**`;
- **JSPs sem `<%` são minoria**: o rewrite de JSP pelo agente é restrito
  pelo juiz congelado do F11 (padrões `_UNSAFE_JSP`) — superfície elegível
  real: JSPs HTML puros (ver `evaluation/rewrite_judge.py`).

## Provenance

- Gerado por G05 (docs/18 §4) a partir do clone real; verificação
  determinística via `tools/siga_locate.py` / `tools/siga_trace.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença
  (`docs/14`). Sem parecer jurídico.
