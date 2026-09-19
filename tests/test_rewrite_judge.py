"""F11: juiz de reescrita JSP/SQL com regras determinísticas."""

from evaluation.rewrite_judge import judge_rewrite


def test_safe_sql_rewrite_passes():
    result = judge_rewrite(
        "db/migration/V105__documento.sql",
        "UPDATE siga.ex_documento SET descr = 'a' WHERE id = 1;",
        "UPDATE siga.ex_documento SET descr = 'b' WHERE id = 1;",
    )
    assert result["verdict"] == "PASS"
    assert result["checks"]["safety_rules"] is True


def test_unsafe_sql_rewrite_is_rejected():
    result = judge_rewrite(
        "db/migration/V105__documento.sql",
        "UPDATE siga.ex_documento SET descr = 'a' WHERE id = 1;",
        "DELETE FROM siga.ex_documento; DROP TABLE siga.ex_documento;",
    )
    assert result["verdict"] == "REJECT"
    assert "DDL destrutivo não permitido" in result["reasons"]
    assert "DML sem WHERE" in result["reasons"]


def test_safe_jsp_rewrite_passes():
    result = judge_rewrite(
        "WEB-INF/page/exDocumento/exibe.jsp",
        '<form action="exDocumento/gravar">old</form>',
        '<form action="exDocumento/gravar">new</form>',
    )
    assert result["verdict"] == "PASS"


def test_unsafe_jsp_rewrite_is_rejected():
    result = judge_rewrite(
        "WEB-INF/page/exDocumento/exibe.jsp",
        '<form action="exDocumento/gravar">old</form>',
        '<% Runtime.getRuntime().exec("sh"); %><a href="https://evil.example">new</a>',
    )
    assert result["verdict"] == "REJECT"
    assert "scriptlet ou execução arbitrária em JSP" in result["reasons"]
    assert "ação ou link externo ao repositório" in result["reasons"]


def test_out_of_scope_and_noop_are_rejected():
    result = judge_rewrite("src/App.java", "class A {}", "class A {}")
    assert result["verdict"] == "REJECT"
    assert "proposta sem alteração" in result["reasons"]
    assert "extensão fora do escopo JSP/SQL" in result["reasons"]
