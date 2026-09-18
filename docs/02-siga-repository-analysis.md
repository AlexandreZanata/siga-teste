# 02 — SIGA repository analysis (`desenvolvimento`, 2026-09-18)

> Todas as afirmações estruturais citam paths reais em `../` (clone somente leitura). Medição via `../scripts/siga_stats.py` — quer dizer, `scripts/siga_stats.py --root ../`. Não assumir que nomes seguem atualizados.

## 1. Escala medida

- Tracked: **13.519**; Java **2.272**; JSP **979**; SQL **553** (`git -C ../ ls-files`).
- `siga-ex`: **506** Java; `sigaex`: **270** Java.
- Testes Java: **61** arquivos `*Test*.java` — cobertura esparsa, reforça verificação via AST/Git em vez de confiar em suite cheia.
- Licença: GNU AGPLv3 (`../LICENSE`).

## 2. Módulos Maven raiz: 24 ativos

`../pom.xml` lista 24 `<module>` ativos; `siga-arq` está comentado (`../pom.xml:54`):

`siga-base`, `siga-ws`, `siga-rel`, `siga-cp`, `siga-sinc-lib`, `siga-ldap`, `siga-web-common`, `siga-spring-module`, `siga-dump`, `siga`, `sigawf`, `siga-wf`, `sigaex`, `siga-ext`, `siga-ex`, `siga-ldap-cli`, `siga-jwt`, `siga-oidc`, `siga-integracao`, `siga-vraptor-module-old`, `siga-vraptor-module`, `sigagc`, `sigasr`, `sigatp`.

Diretórios extras sem módulo ativo (ex.: `../siga-arq/`, `../siga-assinador/`, `../siga-autenticidade/`, `../siga-le/`) exigem checagem caso a caso — não indexar por nome de pasta.

## 3. Foco V1: `siga-ex` + `sigaex`

### 3.1 `../siga-ex/src/main/java/br/gov/jfrj/siga/ex/`

- Entidades + abstratas Hibernate: `AbstractExDocumento.java`, `AbstractExMobil.java`, `AbstractExMovimentacao.java`, `AbstractExFormaDocumento.java`, `AbstractExClassificacao.java`, `AbstractExVia.java` e concretas `ExDocumento.java`, `ExMobil.java`, `ExMovimentacao.java`, `ExFormaDocumento.java`, `ExClassificacao.java`, `ExModelo.java`, `ExMarca.java`.
- Regra de negócio: `../siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/` — `ExBL.java`, `ExTramiteBL.java`, `ExConfiguracaoBL.java`, `ExCompetenciaBL.java`, `ExMarcadorBL.java`, `Ex.java`, `ExParte.java`, `Mesa.java`, `Mesa2.java`.
- PDF/impressão: `../siga-ex/src/main/java/br/gov/jfrj/itextpdf/` (`Documento.java`, `FOP.java`, `Stamp.java`).
- Testes reais: `../siga-ex/src/test/java/br/gov/jfrj/siga/ex/util/` (`DocumentoUtilTest.java`, `ModeloTest.java`, `MascaraClassificacaoTest.java`).

### 3.2 `../sigaex/`

- Camada nova: `../sigaex/src/main/java/br/gov/jfrj/siga/ex/` com `api/`, `service/`, `jpa/`, `relatorio/`, `spring/`, `interceptor/`, `xjus/`; seleção: `../sigaex/src/main/java/br/gov/jfrj/siga/vraptor/` (`ExDocumentoSelecao.java`, `ExMobilSelecao.java`, `ExDocumentoDTO.java`).
- Controllers legados (alvo de trace): `../sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/` — `ExController.java`, `ExDocumentoController.java`, `ExMovimentacaoController.java`, `ExMobilController.java`, `ExModeloController.java`, `ExClassificacaoController.java`, `ExMesa2Controller.java` (+ ~20 outros `Ex*Controller.java`).
- Views: **597** JSPs sob `sigaex` (maior concentração), ex. `../sigaex/` + `siga/src/legacy` como segundo polo.

## 4. Controllers / base web

- Legados VRaptor: **32** em `../siga/src/legacy/java/br/gov/jfrj/siga/vraptor/*Controller.java` (`AcessoController.java`, `BuscaTextualController.java`, `DpPessoaController.java`...).
- Infra VRaptor atual: `../siga-vraptor-module/src/main/java/br/gov/jfrj/siga/vraptor/` (`SigaController.java`, `SigaTransacionalInterceptor.java`, `SigaRoutesParser.java`, `SigaSelecionavelControllerSupport.java`, conversores).
- Base: `../siga-base/src/main/java/br/gov/jfrj/siga/base/` (`Prop.java`, `Contexto.java`, `AplicacaoException.java`, auditoria, `GeraMessageDigest.java`).

## 5. JSP / views

979 JSPs: `sigaex` 597, `sigatp` 147, `siga` 107, `sigasr` 62, `sigawf` 37, `sigagc` 28, `siga-autenticidade` 1. Indexer JSP deve priorizar `sigaex` e resolver includes/tiles por path real, não por nome.

## 6. SQL / migrations (Flyway)

- `../siga-cp/src/main/java/br/gov/jfrj/siga/cp/util/SigaFlyway.java` + `../siga-cp/src/main/resources/db/migration/` (`CORPORATIVO_UTF8_V*.sql`, ex. `V100_0__Finalidade_de_marcador.sql`, `V107_0__create_idx_email_dppessoa.sql`).
- Padrão de nome `CORPORATIVO_UTF8_V<nn>_<m>__<desc>.sql`; indexer SQL deve extrair tabelas lidas/escritas + migration correspondente por entidade.

## 7. Integração / restantes

- `../siga-integracao/` (módulo ativo, `pom.xml` + `src/`); `../siga-ws/`, `../siga-rest-test/`, `../siga-integration-test/` como superfícies de API/teste a mapear na P02.
- `../siga-cp/` = corporativo/pessoas/lotações (ex. `DpLotacaoTest.java`, `CpDaoTest.java`) — grafo deve ligar `Ex*` ↔ `Cp*`/`Dp*` via imports reais.

## 8. Classes centrais para o slice (hipótese a confirmar na P02)

`ExDocumento`, `ExMobil`, `ExMovimentacao`, `ExFormaDocumento`, `ExModelo`, `ExBL`, `ExTramiteBL`, `ExDocumentoController`, `ExMovimentacaoController`, `ExModeloController`. Critério: frequência em imports + presença em BL + controllers + JSPs + migrations. P02 mede centralidade (grau + PageRank no graph) em vez de aceitar esta lista.

## 9. Riscos de modelagem

Cobertura de testes esparsa (61); JSPs legados sem tipagem; VRaptor antigo + Spring novo convivendo; Flyway com centenas de migrations; `siga-arq` comentado pode ressurgir. Tudo isso reforça: fatos no graph (P02), verificação determinística (P03/P04) e splits temporais Git (P04) antes de qualquer treino.
