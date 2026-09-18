"""Fixture SIGA mínima para CI (F03, docs/15-roadmap.md §6).

Reconstrói em árvore temporária os arquivos-âncora do slice real
(siga-ex/sigaex) que os testes pulados no CI consomem: entidades JPA,
controllers VRaptor, JSPs, migration Flyway, pom raiz e repositório Git.
Todos os gabaritos foram extraídos por leitura read-only do clone real
(desenvolvimento, 2026-09-18) e a fixture é gerada a cada uso — nada do
SIGA é copiado em binário. Sem provenance nova: nenhum dado novo é
produzido aqui, só a reprodução dos âncoras já medidos no slice.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from indexer.java_symbols import index_files

_MODULE_NAMES = (
    "siga-base",
    "siga-ws",
    "siga-rel",
    "siga-cp",
    "siga-sinc-lib",
    "siga-ldap",
    "siga-web-common",
    "siga-spring-module",
    "siga-dump",
    "siga",
    "sigawf",
    "siga-wf",
    "sigaex",
    "siga-ext",
    "siga-ex",
    "siga-ldap-cli",
    "siga-jwt",
    "siga-oidc",
    "siga-integracao",
    "siga-vraptor-module-old",
    "siga-vraptor-module",
    "sigagc",
    "sigasr",
    "sigatp",
)

_POM_MODULES = "\n".join(f"        <module>{name}</module>" for name in _MODULE_NAMES)

_POM = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <modelVersion>4.0.0</modelVersion>
  <groupId>br.gov.jfrj.siga</groupId>
  <artifactId>siga-project</artifactId>
  <version>1.0-SNAPSHOT</version>
  <packaging>pom</packaging>
  <modules>
{_POM_MODULES}
<!--\t\t<module>siga-arq</module>-->
  </modules>
</project>
"""

_EX_DOCUMENTO_JAVA = """package br.gov.jfrj.siga.ex;

import javax.persistence.Entity;
import javax.persistence.Table;

@Entity
@Table(name = "siga.ex_documento")
public class ExDocumento {

    private String codigo;

    private ExMobil mobilGeral;

    public String getCodigo() {
        return codigo;
    }

    public ExMobil getMobilGeral() {
        return mobilGeral;
    }
}
"""

_EX_TRAMITE_BL_JAVA = """package br.gov.jfrj.siga.ex.bl;

import br.gov.jfrj.siga.base.util.Utils;
import br.gov.jfrj.siga.ex.ExDocumento;
import br.gov.jfrj.siga.ex.ExMobil;

public class ExTramiteBL {

    public static class Pendencias {

        public long getRecebimentosPendentesSemNotificacoes() {
            return 0L;
        }
    }

    public boolean contemAlgumTramite(ExMobil mobil) {
        return equivaleENaoENulo(mobil) || igual(mobil) || getApensos(mobil) > 0 || hasRecebimento(mobil);
    }

    public boolean equivaleENaoENulo(ExMobil mobil) {
        return true;
    }

    public boolean igual(ExMobil mobil) {
        return false;
    }

    public long getApensos(ExMobil mobil) {
        return 0L;
    }

    public boolean hasRecebimento(ExMobil mobil) {
        return true;
    }    public int calcularTramitesPendentes(ExDocumento doc) {
        boolean tem = contemAlgumTramite(doc.getMobilGeral())
                && equivaleENaoENulo(doc.getMobilGeral())
                && igual(doc.getMobilGeral())
                && getApensos(doc.getMobilGeral()) > 0
                && hasRecebimento(doc.getMobilGeral());
        return tem ? doc.getCodigo().length() : 0;
    }
}"""

_EX_BL_JAVA = """package br.gov.jfrj.siga.ex.bl;

import br.gov.jfrj.siga.ex.ExDocumento;
import br.gov.jfrj.siga.ex.ExMobil;

public class ExBL {

    public void assinarDocumento(ExDocumento doc) {
        cancelarMovimentacao(doc);
    }

    public void cancelarMovimentacao(ExDocumento doc) {
    }

    public void arquivarCorrente(ExMobil mobil) {
    }
}
"""

_EX_MOBIL_JAVA = """package br.gov.jfrj.siga.ex;

import br.gov.jfrj.siga.ex.bl.ExTramiteBL;

public class ExMobil {

    public boolean calcular(ExTramiteBL bl) {
        return bl.contemAlgumTramite(this);
    }
}
"""

_EX_DOC_CONTROLLER_JAVA = """package br.gov.jfrj.siga.vraptor;

import br.com.caelum.vraptor.Controller;
import jakarta.inject.Inject;

@Controller
public class ExDocumentoController extends ExController {

    @Inject
    public ExDocumentoController() {
    }
}
"""

_EX_CONTROLLER_JAVA = """package br.gov.jfrj.siga.vraptor;

public class ExController {
}
"""

_SERVICO_EXEMPLO_JAVA = """package br.gov.jfrj.siga.ex.servico;

public class ServicoExemplo {

    public void executar() {
    }
}
"""

_SERVICO_TEST_JAVA = """package br.gov.jfrj.siga.ex.servico;

public class ServicoExemploTest {

    public void testarExecucao() {
        new ServicoExemplo().executar();
    }
}
"""

_MIGRATION_V104 = """ALTER TABLE siga.ex_documento ADD COLUMN id_doc_principal BIGINT;
UPDATE siga.ex_documento SET id_doc_principal = NULL;
"""

_MIGRATION_V001 = """CREATE TABLE exemplo.servico (
    id BIGINT PRIMARY KEY
);
"""

_EXIBE_JSP = """<%@ page language="java" contentType="text/html; charset=UTF-8" %>
<html>
<body>
  ExDocumento de teste da fixture.
  <%@ include file="marcar.jsp" %>
</body>
</html>
"""

_MARCAR_JSP = """<%@ page language="java" contentType="text/html; charset=UTF-8" %>
<span>marcar.jsp da fixture (botao de marcar do ExDocumento)</span>
"""

_ACESSO_JSP = """<%@ page language="java" contentType="text/html; charset=UTF-8" %>
<jsp:include page="marcar.jsp" />
<span>ExDocumento acessivel pela pagina</span>
"""


def resolve_siga_root(work_root: str | Path) -> Path:
    """Raiz do SIGA para os testes (F03): clone real via env ou fixture gerada.

    `SIGA_CLONE_DIR` apontando para um diretório com `siga-ex/` usa o clone
    real; qualquer outro valor (ausente, vazio ou path inexistente) gera a
    fixture de espelho em árvore temporária. O CI de fundação não define a
    env, então a fixture de espelho é a base dos testes no verify.
    """
    clone_dir = os.environ.get("SIGA_CLONE_DIR", "").strip()
    if clone_dir and (Path(clone_dir) / "siga-ex").is_dir():
        return Path(clone_dir).resolve()
    return build_siga_fixture(Path(tempfile.mkdtemp(prefix="siga-fixture-")))


def build_siga_fixture(dest: str | Path) -> Path:
    """Gera a árvore mínima do SIGA em `dest` (repo git com um commit seed).

    Somente leitura de templates desta fixture; nenhum arquivo é copiado do
    clone real. Retorna o path raiz (com siga-ex/ e sigaex/ presentes).
    """
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)

    # Os 24 módulos ativos do pom raiz existem como diretórios no clone real.
    for name in _MODULE_NAMES:
        (root / name).mkdir(parents=True, exist_ok=True)

    src_ex = root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex"
    src_bl = root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl"
    src_legacy = root / "sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor"
    src_servico = root / "sigaex/src/main/java/br/gov/jfrj/siga/ex/servico"
    migr_dir = root / "siga-ex/src/main/resources/db/migration"
    webapp = root / "sigaex/src/main/webapp/WEB-INF/page/exDocumento"

    for directory in (src_ex, src_bl, src_legacy, src_servico, migr_dir, webapp):
        directory.mkdir(parents=True, exist_ok=True)

    (root / "pom.xml").write_text(_POM, encoding="utf-8")
    (src_ex / "ExDocumento.java").write_text(_EX_DOCUMENTO_JAVA, encoding="utf-8")
    (src_ex / "ExMobil.java").write_text(_EX_MOBIL_JAVA, encoding="utf-8")
    (src_bl / "ExTramiteBL.java").write_text(_EX_TRAMITE_BL_JAVA, encoding="utf-8")
    (src_bl / "ExBL.java").write_text(_EX_BL_JAVA, encoding="utf-8")
    (src_legacy / "ExDocumentoController.java").write_text(_EX_DOC_CONTROLLER_JAVA, encoding="utf-8")
    (src_legacy / "ExController.java").write_text(_EX_CONTROLLER_JAVA, encoding="utf-8")
    (src_servico / "ServicoExemplo.java").write_text(_SERVICO_EXEMPLO_JAVA, encoding="utf-8")
    (src_servico / "ServicoExemploTest.java").write_text(_SERVICO_TEST_JAVA, encoding="utf-8")
    (migr_dir / "SIGA_UTF8_V104__Documento_com_Principal.sql").write_text(_MIGRATION_V104, encoding="utf-8")
    (migr_dir / "V001__servico.sql").write_text(_MIGRATION_V001, encoding="utf-8")
    (webapp / "exibe.jsp").write_text(_EXIBE_JSP, encoding="utf-8")
    (webapp / "marcar.jsp").write_text(_MARCAR_JSP, encoding="utf-8")
    (webapp / "acesso.jsp").write_text(_ACESSO_JSP, encoding="utf-8")

    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@siga.local", "commit", "-qm", "seed")
    return root


def fixture_java_files(root: str | Path) -> list[Path]:
    """Todos os .java da fixture nos módulos do slice, layout determinístico."""
    root_path = Path(root)
    return [
        p
        for module in ("siga-ex", "sigaex")
        for p in sorted((root_path / module).rglob("*.java"))
    ]


def verify_fixture_java(root: str | Path) -> list[dict]:
    """Indexa os .java da fixture; garante que a fixture é parseável antes do uso."""
    recs = index_files(fixture_java_files(root))
    assert recs, "fixture sem arquivos java"
    return recs


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        timeout=60,
    )
