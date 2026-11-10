"""Execute the workflow's protection check against GitHub response shapes."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("rules", "allowed"),
    [
        ([], False),
        ([{"type": "wait_timer", "wait_timer": 10}], False),
        ([{"type": "required_reviewers", "reviewers": []}], False),
        (
            [{"type": "required_reviewers", "reviewers": [{"type": "User"}]}],
            True,
        ),
    ],
)
def test_publication_requires_actual_reviewers(tmp_path, rules, allowed):
    workflow = Path(".github/workflows/docguard-repair.yml").read_text()
    step = workflow.split("name: Require protected publication environment", 1)[1]
    script = textwrap.dedent(step.split("python - <<'PY'\n", 1)[1].split("          PY", 1)[0])
    (tmp_path / "publication-environment.json").write_text(
        json.dumps({"protection_rules": rules}), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=dict(os.environ, RUNNER_TEMP=str(tmp_path)),
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == allowed
    if not allowed:
        assert "Publication requires" in result.stderr
