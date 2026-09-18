"""Estatísticas read-only do clone SIGA (nunca escreve em ROOT)."""
from __future__ import annotations

import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def git_ls_files(root: Path, pattern: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", pattern],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def maven_modules(root: Path) -> list[str]:
    pom = root / "pom.xml"
    if not pom.exists():
        return []
    tree = ET.parse(pom)
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    mods = tree.getroot().findall(".//m:module", ns) or tree.getroot().findall(".//module")
    return [m.text.strip() for m in mods if m.text and m.text.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Medição read-only do SIGA")
    ap.add_argument("--root", default="../", help="Clone do SIGA (somente leitura)")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    total = len(git_ls_files(root, "."))
    java = len(git_ls_files(root, "*.java"))
    jsp = len(git_ls_files(root, "*.jsp"))
    sql = len(git_ls_files(root, "*.sql"))
    mods = maven_modules(root)
    print(f"root={root}")
    print(f"tracked={total} java={java} jsp={jsp} sql={sql}")
    print(f"maven_modules={len(mods)}")
    for m in mods[: args.limit]:
        print(f"  - {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
