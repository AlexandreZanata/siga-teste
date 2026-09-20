"""Discovery de módulos sobre perfil (J01, docs/20 §2).

A lógica é genérica: qualquer raiz com `pom.xml` funciona — o que diz para
olhar `pom.xml` é o perfil (`module_discovery: "maven"`), não código do SIGA.
Cobertura de código é medida com os globs do perfil, restrita a `src/main`
quando existir (convenção Maven herdada do baseline do master plan).
Read-only por construção: apenas leitura de arquivos.
"""

from __future__ import annotations

import fnmatch
import xml.etree.ElementTree as ET
from pathlib import Path

from core.profile import ProjectProfile

MAVEN_NS = {"m": "http://maven.apache.org/POM/4.0.0"}
_MAVEN_CODE_DIRS = ("src/main/java", "src/main/resources", "src/main/webapp")


def maven_modules(repo_root: Path) -> list[str]:
    """Módulos declarados no `pom.xml` raiz (ordem do arquivo; [] sem pom)."""
    pom = repo_root / "pom.xml"
    if not pom.is_file():
        return []
    tree = ET.parse(pom)
    mods = tree.getroot().findall(".//m:module", MAVEN_NS) or tree.getroot().findall(".//module")
    return [m.text.strip() for m in mods if m.text and m.text.strip()]


def discover_modules(repo_root: Path, profile: ProjectProfile) -> list[str]:
    """Descobre módulos pela estratégia declarada no perfil (sem hardcode)."""
    root = Path(repo_root)
    if profile.module_discovery == "maven":
        return maven_modules(root)
    if profile.module_discovery == "gradle":
        return sorted(
            p.parent.relative_to(root).as_posix()
            for p in root.rglob("build.gradle")
            if p.parent != root
        )
    if profile.module_discovery == "explicit":
        return [r for r in profile.module_roots if (root / r).is_dir()]
    if profile.module_discovery == "glob":
        # Módulo = diretório de topo (não-oculto) com ≥1 arquivo casando os code_globs.
        mods: list[str] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            rel = child.relative_to(root).as_posix()
            if any(
                matches_any(f.relative_to(root).as_posix(), profile.code_globs)
                for f in child.rglob("*")
                if f.is_file()
            ):
                mods.append(rel)
        return mods


def module_sources(repo_root: Path, module: str, profile: ProjectProfile) -> list[str]:
    """Arquivos de código do módulo segundo os globs do perfil.

    Se o módulo segue a convenção Maven (`src/main`), a cobertura fica
    restrita a ela — mesmo critério do baseline (master plan) e do G05/G06.
    """
    root = Path(repo_root)
    mroot = root / module
    search_root = mroot / "src/main" if (mroot / "src/main").is_dir() else mroot
    found: set[str] = set()
    for pattern in profile.code_globs:
        sub = pattern.split("/", 1)[1] if "/" in pattern else pattern
        for p in search_root.rglob(sub if "*" in sub else Path(sub).name):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def module_test_sources(repo_root: Path, module: str, profile: ProjectProfile) -> list[str]:
    """Arquivos de teste do módulo (globs de teste do perfil)."""
    root = Path(repo_root)
    found: set[str] = set()
    for pattern in profile.test_globs:
        sub = pattern.split("/", 1)[1] if "/" in pattern else pattern
        for p in (root / module).rglob(sub if "*" in sub else Path(sub).name):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def coverage_by_module(repo_root: Path, profile: ProjectProfile) -> dict[str, dict[str, int]]:
    """Resumo {módulo: {code, tests}} com os globs do perfil (read-only)."""
    summary: dict[str, dict[str, int]] = {}
    for module in discover_modules(repo_root, profile):
        summary[module] = {
            "code": len(module_sources(repo_root, module, profile)),
            "tests": len(module_test_sources(repo_root, module, profile)),
        }
    return summary


def _match_parts(parts: list[str], pparts: list[str]) -> bool:
    """Casa segmentos com o padrão; `**` casa zero ou mais segmentos."""
    if not pparts:
        return not parts
    head = pparts[0]
    if head == "**":
        return any(_match_parts(parts[i:], pparts[1:]) for i in range(len(parts) + 1))
    if not parts or not fnmatch.fnmatch(parts[0], head):
        return False
    return _match_parts(parts[1:], pparts[1:])


def matches_any(path: str, globs: tuple[str, ...]) -> bool:
    """Path relativo casa com algum glob do perfil (`**` = zero ou mais segmentos)."""
    parts = list(Path(path).parts)
    return any(_match_parts(parts, list(Path(pattern).parts)) for pattern in globs)
