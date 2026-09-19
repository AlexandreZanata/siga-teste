"""F10: edição real ponta a ponta sem tocar no clone do SIGA."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from evaluation.editing import apply_unified_patch
from tools.siga_locate import siga_locate


SOURCE = """package example;

public class ServicoController {
    public boolean permitido() {
        return false;
    }
}
"""

PATCH = """--- a/siga-ex/src/main/java/example/ServicoController.java
+++ b/siga-ex/src/main/java/example/ServicoController.java
@@ -3,5 +3,5 @@
 public class ServicoController {
     public boolean permitido() {
-        return false;
+        return true;
     }
 }
"""


def _checkout(root: Path) -> Path:
    target = root / "siga-ex/src/main/java/example/ServicoController.java"
    target.parent.mkdir(parents=True)
    target.write_text(SOURCE, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    return root


def test_locate_edit_and_validate_real_file(tmp_path: Path):
    repo = _checkout(tmp_path)
    candidates = siga_locate("ServicoController", repo=repo, limit=5)
    assert any(Path(candidate["file"]).name == "ServicoController.java" for candidate in candidates)

    result = apply_unified_patch(repo, PATCH)
    target = repo / result["path"]
    assert result["path"] == "siga-ex/src/main/java/example/ServicoController.java"
    assert result["before_sha256"] != result["after_sha256"]
    assert result["changed_lines"] > 0
    assert "return true;" in target.read_text(encoding="utf-8")


def test_patch_rejects_path_escape_without_writing(tmp_path: Path):
    repo = _checkout(tmp_path)
    original = (repo / "siga-ex/src/main/java/example/ServicoController.java").read_text(encoding="utf-8")
    unsafe = PATCH.replace("siga-ex/src/main/java/example/ServicoController.java", "../../outside.java")

    with pytest.raises(ValueError, match="fora do checkout"):
        apply_unified_patch(repo, unsafe)

    assert (repo / "siga-ex/src/main/java/example/ServicoController.java").read_text(encoding="utf-8") == original


def test_patch_rejects_stale_context_without_writing(tmp_path: Path):
    repo = _checkout(tmp_path)
    target = repo / "siga-ex/src/main/java/example/ServicoController.java"
    target.write_text(SOURCE.replace("return false;", "return maybe;"), encoding="utf-8")
    original = target.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="contexto"):
        apply_unified_patch(repo, PATCH)

    assert target.read_text(encoding="utf-8") == original
