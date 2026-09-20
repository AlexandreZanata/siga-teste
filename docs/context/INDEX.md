# Biblioteca de contexto SIGA — índice

> Biblioteca de contexto para devs e IAs (docs/18 §4, G05/G06). Cada página é gerada/validada contra o clone real do SIGA — **nenhum path ou símbolo inventado**: existência no HEAD e resolução por `siga_locate` (tools determinísticas deste repo).

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Regra:** página desatualizada = recalcular contra o HEAD atual e atualizar o `source_commit` acima; disparidade entre páginas é sempre detectável por este campo.

## Páginas

| Módulo | Papel | Página | Tamanho medido |
|---|---|---|---|
| `siga` | módulo web raiz (portais, principal, legacy VRaptor do corpo) | [siga.md](siga.md) | 87 `.java`, 107 JSPs |
| `siga-base` | base compartilhada (propriedades, utilitários, DpPessoa/DpLotacao) | [siga-base.md](siga-base.md) | 70 `.java` |
| `siga-cp` | núcleo corporativo (configurações, personas, arquivos blob, migrações) | [siga-cp.md](siga-cp.md) | 247 `.java`, 222 SQLs |
| `siga-dump` | exportação/dump de dados | [siga-dump.md](siga-dump.md) | 1 `.java` |
| `siga-ex` | core de negócio documental (entidades, BL, logic, DAO) | [siga-ex.md](siga-ex.md) | 501 `.java`, 172 SQLs |
| `siga-ext` | extensões pontuais do expediente | [siga-ext.md](siga-ext.md) | 6 `.java` |
| `siga-integracao` | integrações externas do expediente (serviços e clients) | [siga-integracao.md](siga-integracao.md) | 123 `.java` |
| `siga-jwt` | emissão/validação de JWT para APIs | [siga-jwt.md](siga-jwt.md) | 8 `.java` |
| `siga-ldap` | integração LDAP do núcleo | [siga-ldap.md](siga-ldap.md) | 5 `.java` |
| `siga-ldap-cli` | cliente leve de LDAP | [siga-ldap-cli.md](siga-ldap-cli.md) | 1 `.java` |
| `siga-oidc` | autenticação OIDC (SSO) | [siga-oidc.md](siga-oidc.md) | 7 `.java` |
| `siga-rel` | infraestrutura de relatórios dinâmicos (templates Freemarker) | [siga-rel.md](siga-rel.md) | 8 `.java` |
| `siga-sinc-lib` | biblioteca de sincronização (LRI/legado) | [siga-sinc-lib.md](siga-sinc-lib.md) | 14 `.java` |
| `siga-spring-module` | colagem Spring compartilhada entre módulos web | [siga-spring-module.md](siga-spring-module.md) | 25 `.java` |
| `siga-vraptor-module` | tags/componentes VRaptor compartilhados | [siga-vraptor-module.md](siga-vraptor-module.md) | 30 `.java` |
| `siga-vraptor-module-old` | módulo VRaptor legado (mantido por compatibilidade) | [siga-vraptor-module-old.md](siga-vraptor-module-old.md) | 57 `.java` |
| `siga-web-common` | infra web comum (JPA, Freemarker padrão, suporte JEE) | [siga-web-common.md](siga-web-common.md) | 46 `.java` |
| `siga-wf` | núcleo de workflow (WfBL, modelos de procedimento, migrações) | [siga-wf.md](siga-wf.md) | 90 `.java`, 40 SQLs |
| `siga-ws` | serviços SOAP/expostos de integração do expediente | [siga-ws.md](siga-ws.md) | 15 `.java` |
| `sigaex` | camada web do expediente (controllers VRaptor/Spring + JSPs) | [sigaex.md](sigaex.md) | 237 `.java`, 597 JSPs |
| `sigagc` | gestão de contratos (web + integração) | [sigagc.md](sigagc.md) | 45 `.java`, 28 JSPs, 12 SQLs |
| `sigasr` | SIGA-SR (solicitações/requisições: web + núcleo) | [sigasr.md](sigasr.md) | 181 `.java`, 62 JSPs, 39 SQLs |
| `sigatp` | SIGA-TP (acompanhamento processual/tabelas: web + núcleo) | [sigatp.md](sigatp.md) | 170 `.java`, 147 JSPs, 51 SQLs |
| `sigawf` | camada web do workflow (controllers + JSPs de procedimento) | [sigawf.md](sigawf.md) | 71 `.java`, 37 JSPs |

## Cobertura

- **24 de 24 módulos Maven ativos** (`pom.xml` raiz) — lote 1 (núcleo `siga-ex`, `sigaex`) + lotes 2–N (G06, docs/18 §4);
- Convenção de nome: `docs/context/<modulo>.md`.

## Como usar

- Dev/IA chegando num domínio: começar pela página do módulo; `siga_locate` para achar símbolos citados; `siga_trace` para o fluxo;
- Agente com MCP: `siga_context` embute as páginas relevantes no campo `context_library` da cápsula (integração G06).

## Licença

Conteúdo derivado de código AGPLv3 (SIGA) — herda as obrigações da licença (`docs/14`). Sem parecer jurídico.
