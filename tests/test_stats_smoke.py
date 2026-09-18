from pathlib import Path


def test_stats_script_exists():
    assert (Path(__file__).resolve().parent.parent / "scripts" / "siga_stats.py").exists()


def test_docs_readme_exists():
    assert (Path(__file__).resolve().parent.parent / "docs" / "README.md").exists()
