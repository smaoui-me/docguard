import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("target", "ref", "licensed", "allowed"),
    [
        ("build", "refs/heads/master", False, True),
        ("pypi", "refs/heads/master", True, False),
        ("testpypi", "refs/tags/v0.2.0", True, False),
        ("ghcr", "refs/tags/v0.1.0", False, False),
        ("pypi", "refs/tags/v0.1.0", True, True),
    ],
)
def test_release_identity_gate(tmp_path, target, ref, licensed, allowed):
    workflow = Path(".github/workflows/release.yml").read_text()
    step = workflow.split("name: Check release identity", 1)[1]
    script = textwrap.dedent(
        step.split("python - <<'PY'\n", 1)[1].split("          PY", 1)[0]
    )
    project = '[project]\nname="docguard"\nversion="0.1.0"\n'
    if licensed:
        project += 'license="MIT"\n'
        (tmp_path / "LICENSE").write_text("Test fixture only")
    (tmp_path / "pyproject.toml").write_text(project)
    output = tmp_path / "outputs"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=dict(os.environ, TARGET=target, GITHUB_REF=ref, GITHUB_OUTPUT=str(output)),
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == allowed, result.stderr
    if allowed:
        assert output.read_text().strip() == "version=0.1.0"
    else:
        assert not output.exists()
