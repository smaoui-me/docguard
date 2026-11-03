import json
import os
from unittest.mock import patch

from docguard.cli import main
from docguard.code.index import index_repository
from docguard.code.snapshots import save_snapshot


def test_env_to_groq_dry_run_generation_preview_and_apply(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DOCGUARD_AI_PROVIDER=groq\nDOCGUARD_MODEL=openai/gpt-oss-120b\nGROQ_API_KEY=fake-groq-key",
        encoding="utf-8",
    )
    source = tmp_path / "price.py"
    source.write_text("def total(price):\n    return price\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    save_snapshot(index_repository(tmp_path), baseline)
    source.write_text("def total(price):\n    return price * 1.2\n", encoding="utf-8")
    doc = tmp_path / "README.md"
    doc.write_text("Returns price unchanged.", encoding="utf-8")
    mapping = tmp_path / "map.json"
    mapping.write_text(
        '{"schema_version":1,"documents":{"README.md":["price.py:total"]}}',
        encoding="utf-8",
    )
    args = [
        "suggest",
        str(baseline),
        "--root",
        str(tmp_path),
        "--mapping",
        str(mapping),
    ]
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("docguard.ai.provider.build_opener") as network,
    ):
        requests = tmp_path / "requests.json"
        assert main(args + ["--dry-run", "--output", str(requests)]) == 0
        network.assert_not_called()
        payload = json.loads(requests.read_text())["requests"][0]
        assert payload["model"] == "openai/gpt-oss-120b"
        assert payload["messages"][1]["role"] == "user"
        assert "fake-groq-key" not in requests.read_text()
        decision = {
            "action": "revise",
            "summary": "Multiplier changed",
            "content": "Returns price multiplied by 1.2.",
            "warnings": [],
        }
        network.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(decision)},
                    }
                ]
            }
        ).encode()
        proposal = tmp_path / "proposal.json"
        assert main(args + ["--output", str(proposal)]) == 0
        assert (
            network.return_value.open.call_args.args[0].get_header("Authorization")
            == "Bearer fake-groq-key"
        )
        assert doc.read_text() == "Returns price unchanged."
        apply = [
            "apply-proposal",
            str(proposal),
            "--root",
            str(tmp_path),
            "--document",
            "README.md",
        ]
        assert main(apply + ["--check"]) == 0
        assert doc.read_text() == "Returns price unchanged."
        assert main(apply) == 0
        assert doc.read_text() == decision["content"]
        assert main(apply) == 2
