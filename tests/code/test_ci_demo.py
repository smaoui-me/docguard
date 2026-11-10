import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.git_proposals import suggest_git
from docguard.git_review import _git


def test_demo_scenarios_application_tests_and_document_routes(tmp_path):
    path = Path("examples/create_ci_demo.py")
    spec = importlib.util.spec_from_file_location("create_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "demo"
    commits = module.create_demo(root)
    assert set(commits) == {
        "main",
        "scenario/stale",
        "scenario/already-correct",
        "scenario/missing-evidence",
        "scenario/no-impact",
    }
    assert _git(root, "status", "--porcelain") == b""
    assert _git(root, "remote") == b""
    with pytest.raises(ValueError, match="new demo"):
        module.create_demo(root)
    for branch in commits:
        _git(root, "checkout", branch)
        app = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        assert app.returncode == 0, app.stderr
        if branch == "main":
            continue
        output = tmp_path / (branch.split("/")[1] + ".json")
        suggest_git(
            root,
            commits["main"],
            commits[branch],
            "docguard-map.json",
            output,
            AIConfig("groq", "test", ""),
            dry_run=True,
        )
        data = json.loads(output.read_text())
        if branch in {"scenario/stale", "scenario/already-correct"}:
            assert len(data["requests"]) == 1
        else:
            assert data["requests"] == []
            if branch == "scenario/missing-evidence":
                assert (
                    data["review"]["claim_requirements"]["docs/prices.md"]["status"]
                    != "ready"
                )
    repair = (root / ".github/workflows/docguard-repair.yml").read_text()
    assert repair.count("repository: smaoui-me/docguard") == 2
    assert repair.count(module.PIN) == 2
    assert "default: docs/prices.md" in repair
    assert "runs-on: ubuntu-latest" in repair
