# siga-cp — núcleo corporativo (configurações, personas, arquivos blob, migrações)

> Biblioteca de contexto SIGA (docs/18 §4, G06 — gerada por `scripts/gen_context_docs.py`). Fonte de grounding: clone do SIGA em `../` @ `48610bd65046` — cada símbolo abaixo foi resolvido por `siga_locate` real e as contagens são medidas no HEAD.

- **source_commit (SIGA):** `48610bd6504692ad3f2e99ef318beb84e2668fd6`
- **Tamanho medido:** 247 arquivos `.java`; 222 migrações/SQLs.

## Responsabilidade

Módulo **núcleo corporativo (configurações, personas, arquivos blob, migrações)** do SIGA (mapeamento do `pom.xml` raiz e docs/00–05).

### Regra de negócio

- `siga-cp/src/main/java/br/gov/jfrj/siga/cp/bl/CpAmbienteEnumBL.java` — símbolo `CpAmbienteEnumBL` (resolvido por `siga_locate`).
- `siga-cp/src/main/java/br/gov/jfrj/siga/cp/bl/CpBL.java` — símbolo `CpBL` (resolvido por `siga_locate`).
- `siga-cp/src/main/java/br/gov/jfrj/siga/cp/bl/CpCompetenciaBL.java` — símbolo `CpCompetenciaBL` (resolvido por `siga_locate`).
- `siga-cp/src/main/java/br/gov/jfrj/siga/cp/bl/CpConfiguracaoBL.java` — símbolo `CpConfiguracaoBL` (resolvido por `siga_locate`).
- `siga-cp/src/main/java/br/gov/jfrj/siga/cp/bl/CpSubstituicaoBL.java` — símbolo `CpSubstituicaoBL` (resolvido por `siga_locate`).
- `siga-cp/src/main/java/br/gov/jfrj/siga/ldap/sinc/LdapBL.java` — símbolo `LdapBL` (resolvido por `siga_locate`).

### Serviços

- `siga-cp/src/main/java/br/gov/jfrj/siga/gi/service/impl/GiServiceImpl.java` — símbolo `GiServiceImpl` (resolvido por `siga_locate`).
- `siga-cp/src/main/java/br/gov/jfrj/siga/gi/integracao/IntegracaoLdapViaWebService.java` — símbolo `IntegracaoLdapViaWebService` (resolvido por `siga_locate`).

### Acesso a dados

- `siga-cp/src/main/java/br/gov/jfrj/siga/dp/dao/CpDao.java` — símbolo `CpDao` (resolvido por `siga_locate`).

## Como usar

- Para reverificar um símbolo citado: `python -c "from tools.siga_locate import siga_locate; print(siga_locate('<Simbolo>', repo='..'))"`;
- Página gerada deterministicamente: regenerar com `python -m scripts.gen_context_docs` após atualizar o clone.

## Provenance

- Gerada por G06 (docs/18 §4) a partir do clone real; verificação determinística via `tools/siga_locate.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença (`docs/14`). Sem parecer jurídico.
