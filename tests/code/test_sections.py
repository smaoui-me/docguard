import json
from pathlib import Path

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository, load_cases
from docguard.ai.files import ProposalError
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.docs.sections import (
    replace_section,
    select_section,
    validate_section_edit,
)
from docguard.git_review import _git


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_byte_preservation_unicode_nested_and_fences(newline):
    raw = b"\xef\xbb\xbf# API\nintro \xc3\xa9\n" + newline.join(
        [
            b"## Prices",
            b"old",
            b"```python",
            b"## fake",
            b"```",
            b"### Detail",
            b"old",
            b"## Support",
            b"keep\t ",
            b"",
        ]
    )
    path = ("# API", "## Prices")
    old = select_section(raw, path)
    result = replace_section(raw, path, "## Prices\nnew\n")
    assert result == raw[: old.start] + b"## Prices\nnew\n" + raw[old.end :]
    validate_section_edit(raw.decode("utf-8"), result.decode("utf-8"), path)
    with pytest.raises(ProposalError, match="outside"):
        validate_section_edit(
            raw.decode("utf-8"), result.decode("utf-8").replace("keep", "changed"), path
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"# A\nx\n# A\ny\n",
        b"# Other\n",
        b"# A\n```\nunclosed",
        b"# A\nTitle\n===\n",
        b"# A\n<!-- hidden -->\n",
        b"# A\n    code\n",
        b"# A\n##\nother section",
        b"# A\n  ## Nested\n",
    ],
)
def test_ambiguous_missing_or_unsupported_markdown_rejected(raw):
    with pytest.raises(ProposalError):
        select_section(raw, ("# A",))


@pytest.mark.parametrize(
    "replacement",
    ["# B\nx\n", "# A\nx\n# Escape\nx\n", "# A\n```\n", "# A\nno boundary"],
)
def test_replacement_cannot_escape_heading(replacement):
    with pytest.raises(ProposalError):
        replace_section(b"# A\nold\n# B\nkeep\n", ("# A",), replacement)


def test_git_section_generation_preview_apply_and_tampering(tmp_path):
    case = load_cases(Path("evaluations/git_cases.toml"))[0]
    root = tmp_path / "repo"
    base, _ = create_case_repository(case, root)
    raw = (
        b"# API\r\nintro \xc3\xa9\n## Connection\r\nOld claim.\r\n## Support\nKEEP \t\n"
    )
    (root / "README.md").write_bytes(raw)
    (root / "docguard-map.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "documents": {
                    "README.md": {
                        "entity_ids": case["entity_ids"],
                        "claims": [],
                        "section": ["# API", "## Connection"],
                    }
                },
            }
        )
    )
    _git(root, "-c", "core.autocrlf=false", "add", ".")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "section mapping",
    )
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    output = tmp_path / "proposal.json"

    def generator(model, context):
        assert "KEEP" not in context["document_text"]
        return {
            "action": "revise",
            "summary": "Document timeout",
            "content": "## Connection\nTimeout defaults to 30.\n",
            "warnings": [],
            "evidence_ids": [context["evidence"][-1]["id"]],
        }

    suggest_git(
        root,
        base,
        head,
        "docguard-map.json",
        output,
        AIConfig("groq", "test", ""),
        generator=generator,
    )
    assert "Timeout" in apply_git_proposal(output, root, "README.md", check=True)
    assert (root / "README.md").read_bytes() == raw
    original_artifact = output.read_bytes()
    tampered = json.loads(original_artifact)
    tampered["proposals"][0]["proposal"]["content"] = tampered["proposals"][0][
        "proposal"
    ]["content"].replace("KEEP", "BAD")
    output.write_text(json.dumps(tampered))
    with pytest.raises(ProposalError, match="outside"):
        apply_git_proposal(output, root, "README.md")
    output.write_bytes(original_artifact)
    apply_git_proposal(output, root, "README.md")
    expected = replace_section(
        raw, ("# API", "## Connection"), "## Connection\r\nTimeout defaults to 30.\r\n"
    )
    assert (root / "README.md").read_bytes() == expected
    with pytest.raises(ProposalError, match="Document changed"):
        apply_git_proposal(output, root, "README.md")
