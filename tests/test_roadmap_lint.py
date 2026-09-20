from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "roadmap_lint.py"

spec = importlib.util.spec_from_file_location("roadmap_lint", SCRIPT)
roadmap_lint = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(roadmap_lint)

def test_roadmap_manifest_and_links_are_consistent():
    assert roadmap_lint.lint(ROOT, ROOT / "docs" / "roadmap" / "manifest.json") == []

def test_cycle_detection():
    graph = {"A": ["B"], "B": ["C"], "C": ["A"]}
    assert roadmap_lint.check_cycle(graph)

def test_acyclic_detection():
    graph = {"A": [], "B": ["A"], "C": ["B"]}
    assert roadmap_lint.check_cycle(graph) == []
