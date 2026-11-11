"""Verify an installed distribution outside its checkout, without API calls.

Run with the Python interpreter from the clean environment being tested.
"""

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory


def verify() -> None:
    with TemporaryDirectory(prefix="docguard-install-") as directory:
        work = Path(directory)
        env = dict(os.environ)
        for key in ("PYTHONPATH", "GROQ_API_KEY", "OPENAI_API_KEY"):
            env.pop(key, None)
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

        def run(args: list[str], expected: int = 0) -> str:
            result = subprocess.run(
                args, cwd=work, env=env, capture_output=True, text=True, timeout=120
            )
            if result.returncode != expected:
                raise RuntimeError(
                    f"Command {args[0]} returned {result.returncode}: {result.stderr}"
                )
            return result.stdout

        def cli(*args: str, expected: int = 0) -> str:
            return run([sys.executable, "-I", "-m", "docguard", *args], expected)

        print(cli("--version").strip())
        cli("--help")
        # Installed console entry point, not the checkout's Python module path.
        executable = Path(sys.executable).parent / (
            "docguard.exe" if os.name == "nt" else "docguard"
        )
        run([str(executable), "--help"])
        repo = work / "repo"
        repo.mkdir()
        source = repo / "api.py"
        source.write_text("def total(price):\n    return price\n", encoding="utf-8")
        (repo / "README.md").write_text("total(price) returns price unchanged.\n")
        (repo / "docguard-map.json").write_text(
            json.dumps(
                {"schema_version": 1, "documents": {"README.md": ["api.py:total"]}}
            )
        )
        cli("snapshot", str(repo), "--output", "baseline.json")
        cli("compare", "baseline.json", "--root", str(repo))

        def git(*args: str) -> str:
            return run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "core.hooksPath=" + os.devnull,
                    "-c",
                    "commit.gpgsign=false",
                    *args,
                ]
            ).strip()

        git("init")
        git("config", "user.name", "Installation Test")
        git("config", "user.email", "test@example.invalid")
        git("config", "core.autocrlf", "false")
        git("add", ".")
        git("commit", "-m", "baseline")
        base = git("rev-parse", "HEAD")
        source.write_text(
            "def total(price):\n    return price * 1.2\n", encoding="utf-8"
        )
        cli("compare", "baseline.json", "--root", str(repo), expected=1)
        git("add", ".")
        git("commit", "-m", "behavior change")
        head = git("rev-parse", "HEAD")
        report = json.loads(
            cli(
                "review-git",
                "--root",
                str(repo),
                "--base",
                base,
                "--head",
                head,
                "--format",
                "json",
                "--mapping",
                "docguard-map.json",
                expected=1,
            )
        )
        assert report["counts"]["documents"] == 1
        cli(
            "suggest-git",
            "--root",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--document",
            "README.md",
            "--mapping",
            "docguard-map.json",
            "--dry-run",
            "--output",
            "requests.json",
        )
        assert len(json.loads((work / "requests.json").read_text())["requests"]) == 1
        cli("evaluate-ai", "--output", "evaluation.json")
        evaluation = json.loads((work / "evaluation.json").read_text())
        assert evaluation["mode"] == "offline-fixtures"
        assert evaluation["passed"] == evaluation["total"] and evaluation["errors"] == 0
        # The offline review page ships inside the installed package, without assets
        # from this checkout or any browser/runtime dependency.
        context = {"document_text": "# Fixture\n", "evidence": []}
        packet = {
            "schema_version": 1,
            "kind": "docguard.review-packet",
            "cases": [
                {
                    "case": "installation-fixture",
                    "exposure": "synthetic-installation-fixture",
                    "provenance": {
                        "pr_url": "https://github.com/example/fixture/pull/1",
                        "repository_url": "https://github.com/example/fixture",
                        "upstream_base": base,
                        "upstream_head": head,
                        "variant": "synthetic",
                        "scope": "Installation fixture; no upstream PR claim",
                        "license_text": "Synthetic fixture",
                        "document_selections": {
                            "head": {
                                "upstream_revision": head,
                                "path": "README.md",
                                "start_line": 1,
                            }
                        },
                    },
                    "contexts": {k: context for k in ("mapped", "direct")},
                    "context_sha256": {
                        k: sha256(
                            json.dumps(context, sort_keys=True).encode()
                        ).hexdigest()
                        for k in ("mapped", "direct")
                    },
                }
            ],
        }
        (work / "packet.json").write_text(json.dumps(packet))
        cli("review-ui", "packet.json", "--output", "review.html")
        assert "DocGuard / Evidence review" in (work / "review.html").read_text(
            encoding="utf-8"
        )
        cli("evaluate-experiment", "--help")
        cli("score-experiment", "--help")
        source.write_text("def broken(\n", encoding="utf-8")
        cli("snapshot", str(repo), "--output", "invalid.json", expected=2)
        assert not (work / "invalid.json").exists()
        print(
            "PASS: clean installation, Git review, offline evaluation, packaged review UI, and error exits"
        )


if __name__ == "__main__":
    verify()
