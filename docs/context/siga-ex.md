# siga-ex — núcleo de negócio documental

> Biblioteca de contexto SIGA (docs/18 §4, G05). Fonte de grounding:
> clone do SIGA em `../` @ `48610bd65046` — cada path abaixo conferido por
> existência no HEAD e cada símbolo resolvido por `siga_locate`/`siga_trace`
> real (tools deste repo). Para reverificar um símbolo:
> `python -c "from tools.siga_locate import siga_locate; print(siga_locate('ExMobil', repo='..'))"`.

- **source_commit (SIGA):** `48610bd65046`
- **Tamanho medido:** 501 arquivos `.java` (sem JSPs); 25 módulos Maven no `pom.xml` raiz.

## Responsabilidade

Módulo **biblioteca/core** (sem camada web): contém o modelo de documento
eletrônico do SIGA — entidades, regras de negócio, configurações e acesso a
dados. Não conhece HTTP/JSP; quem expõe isso ao usuário é o módulo `sigaex`.

## Entry points (arquivos reais no HEAD)

- `siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java` — classe central de
  regras de negócio (movimentação, juntada, cancelamento, assinatura).
- `siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java`,
  `.../ExMobil.java`, `.../ExMovimentacao.java` — entidades centrais
  (documento, via/mobil, movimentação); cada uma estende um `Abstract*`
  correspondente (`AbstractExDocumento.java`, `AbstractExMobil.java`) —
  `siga_trace('ExMobil')` resolve para `AbstractExMobil.java`.
- `siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExCompetenciaBL.java` —
  competências/permissions (quem pode fazer o quê).
- `siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExConfiguracaoBL.java` —
  configurações por tipo/configuração.
- `siga-ex/src/main/java/br/gov/jfrj/siga/ex/logic/ExPodeJuntar.java` —
  padrão das classes `logic/*`: predicados nomeados usados pelas BLs
  (ex.: `ExPodeJuntar`, `ExPodeCancelarMovimentacao`);
- `siga-ex/src/main/java/br/gov/jfrj/siga/hibernate/ExDao.java` — DAO geral;
  **atenção**: apesar do nome, o pacote é `siga/hibernate` (dentro do
  próprio módulo), não um módulo separado.

## Como adicionar feature / corrigir bug

1. Regra de negócio nova → método em `ExBL` (ou BL específica) + predicado
   em `siga-ex/src/main/java/br/gov/jfrj/siga/ex/logic/` se envolver permissão;
2. Permissões por perfil/lotação → `ExCompetenciaBL` + configuração
   (`ExConfiguracaoBL`);
3. Nova consulta/dados → método no `siga-ex/src/main/java/br/gov/jfrj/siga/hibernate/ExDao.java`;
4. Exposição ao usuário → pertence ao `sigaex` (controllers/JSP), não aqui.

## Armadilhas (grounded)

- **Herança `Abstract*`**: `ExDocumento`, `ExMobil` etc. estendem
  `siga-ex/src/main/java/br/gov/jfrj/siga/ex/AbstractExDocumento.java` e
  `siga-ex/src/main/java/br/gov/jfrj/siga/ex/AbstractExMobil.java` —
  alteração de modelo toca os dois arquivos (trace real: `ExMobil` →
  `AbstractExMobil`);
- **`ExDao` fora do lugar esperado**: `siga/hibernate/ExDao.java` — procurar
  por "ExDao" no pacote `ex/` não encontra (falso negativo comum);
- **Módulo sem web**: qualquer necessidade de tela/endpoint não é deste
  módulo — siga para `sigaex` (ver `sigaex.md`).

## Provenance

- Gerado por G05 (docs/18 §4) a partir do clone real; verificação
  determinística via `tools/siga_locate.py` / `tools/siga_trace.py`;
- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença
  (`docs/14`). Sem parecer jurídico.
