import json

import pytest

from docguard.ai.evidence import DependencyEvidence
from docguard.code.index import index_repository


def collect(root, files, seed="api.py:total", **limits):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    collector = DependencyEvidence(root, index_repository(root))
    return collector.expand([seed], "after", "a" * 40, **limits)


def test_follows_alias_relative_import_constant_and_never_executes(tmp_path):
    additions, gaps = collect(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/api.py": "from .helpers import transform as convert\ndef total(x):\n    return convert(x)\n",
            "pkg/helpers.py": "raise RuntimeError('must not execute')\nRATE = 1.2\ndef transform(x):\n    return x * RATE\n",
        },
        "pkg/api.py:total",
    )
    assert [e["id"] for e in additions] == [
        "after:pkg/helpers.py:transform",
        "after:pkg/helpers.py:@binding:2",
    ]
    assert "RATE = 1.2" in additions[-1]["text"]
    assert not gaps
    assert all(e["revision"] == "a" * 40 and len(e["sha256"]) == 64 for e in additions)


def test_module_alias_and_literal_default(tmp_path):
    additions, _ = collect(
        tmp_path,
        {
            "api.py": "import helpers as h\nLIMIT = 5\ndef total(x=LIMIT):\n    return h.transform(x) + h.RATE\n",
            "helpers.py": "RATE = 2\ndef transform(x):\n    return x\n",
        },
    )
    text = "\n".join(e["text"] for e in additions)
    assert "LIMIT = 5" in text and "RATE = 2" in text and "def transform" in text


@pytest.mark.parametrize(
    "prefix,body",
    [
        ("def helper(x): return x\n", "def total(helper): return helper(1)\n"),
        (
            "def helper(x): return x\ndef helper(x): return x+1\n",
            "def total(x): return helper(x)\n",
        ),
        (
            "if condition:\n    def helper(x): return x\n",
            "def total(x): return helper(x)\n",
        ),
        (
            "def helper(x): return x\nhelper = external\n",
            "def total(x): return helper(x)\n",
        ),
        (
            "def helper(x): return x\n",
            "def total(x):\n    from external import helper\n    return helper(x)\n",
        ),
    ],
)
def test_ambiguous_conditional_shadowed_bindings_not_guessed(tmp_path, prefix, body):
    additions, gaps = collect(tmp_path, {"api.py": prefix + body})
    assert additions == []
    assert gaps


def test_cycles_and_limits_are_explicit_and_deterministic(tmp_path):
    files = {
        "api.py": "def total(x): return first(x)\ndef first(x): return second(x)\ndef second(x): return total(x)\n"
    }
    full, _ = collect(tmp_path, files)
    repeated, _ = collect(tmp_path, files)
    assert full == repeated and len(full) == 2
    for limits, reason in [
        ({"max_chars": 0}, "budget"),
        ({"max_items": 0}, "budget"),
        ({"max_depth": 0}, "depth"),
    ]:
        items, gaps = collect(tmp_path, files, **limits)
        assert not items and reason in gaps[0]["reason"]


def test_external_and_dynamic_calls_are_reported(tmp_path):
    additions, gaps = collect(
        tmp_path,
        {
            "api.py": "from absent import external\ndef total(x): return x.transform(external(x))\n"
        },
    )
    assert not additions
    assert {gap["reference"] for gap in gaps} == {"external", "x.transform"}


def test_duplicate_module_candidates_are_not_guessed(tmp_path):
    additions, gaps = collect(
        tmp_path,
        {
            "api.py": "from helpers import transform\ndef total(x): return transform(x)\n",
            "one/helpers.py": "def transform(x): return x\n",
            "two/helpers.py": "def transform(x): return x+1\n",
        },
    )
    assert not additions and gaps


def test_decorated_dependency_preserves_decorator_text(tmp_path):
    additions, _ = collect(
        tmp_path,
        {
            "api.py": "def total(x): return helper(x)\n@external_decorator\ndef helper(x): return x\n"
        },
    )
    assert additions[0]["start_line"] == 2
    assert additions[0]["text"].startswith("@external_decorator")


def test_constructor_and_nested_scope_handling(tmp_path):
    additions, gaps = collect(
        tmp_path,
        {
            "api.py": "class Value:\n    def __init__(self, x): self.x = x\ndef total(x):\n    def nested(): return secret()\n    return Value(x)\n"
        },
    )
    assert [e["id"] for e in additions] == ["after:api.py:Value.__init__"]
    assert "secret" not in json.dumps(gaps)


def test_closure_and_star_import_are_not_mistaken_for_module_bindings(tmp_path):
    items, gaps = collect(
        tmp_path,
        {
            "api.py": "def helper(x): return x\ndef outer(helper):\n    def inner(x): return helper(x)\n    return inner\n"
        },
        "api.py:outer.inner",
    )
    assert not items and "closure" in gaps[0]["reason"]
    items, gaps = collect(
        tmp_path,
        {
            "api.py": "def helper(x): return x\nfrom external import *\ndef total(x): return helper(x)\n"
        },
    )
    assert not items and gaps


def test_cross_module_import_cycle_stays_unresolved(tmp_path):
    items, gaps = collect(
        tmp_path,
        {
            "api.py": "from a import helper\ndef total(x): return helper(x)\n",
            "a.py": "from b import helper\n",
            "b.py": "from a import helper\n",
        },
    )
    assert not items and gaps


def test_evidence_payload_budget_is_in_serialized_characters(tmp_path):
    items, gaps = collect(
        tmp_path,
        {
            "api.py": "def total(x): return helper(x)\ndef helper(x): return 'large\\n' * x\n"
        },
        max_chars=20,
    )
    assert not items and "budget" in gaps[0]["reason"]


def test_direct_git_evidence_reconstructed_at_apply(tmp_path):
    from docguard.ai.config import AIConfig
    from docguard.ai.dataset import create_case_repository
    from docguard.ai.files import ProposalError
    from docguard.ai.git_proposals import apply_git_proposal, suggest_git

    root = tmp_path / "repo"
    base, head = create_case_repository(
        {
            "before": "def total(x): return helper(x)\ndef helper(x): return x\n",
            "after": "def total(x): return helper(x) + 1\ndef helper(x): return x * 2\n",
            "before_document": "Returns x.",
            "document": "Returns x.",
            "entity_ids": ["api.py:total"],
        },
        root,
    )
    output = tmp_path / "proposal.json"

    def generate(model, context):
        assert "after:api.py:helper" in {e["id"] for e in context["evidence"]}
        assert context["evidence_selection"]["policy"] == "direct"
        return {
            "action": "revise",
            "summary": "Updated",
            "content": "Returns 2*x + 1.",
            "warnings": [],
            "evidence_ids": ["after:api.py:helper"],
        }

    suggest_git(
        root,
        base,
        head,
        "docguard-map.json",
        output,
        AIConfig("groq", "test", ""),
        generator=generate,
        evidence_policy="direct",
    )
    assert "+Returns 2*x + 1." in apply_git_proposal(
        output, root, "README.md", check=True
    )
    data = json.loads(output.read_text())
    data["evidence_policy"] = "mapped"
    output.write_text(json.dumps(data))
    with pytest.raises(ProposalError, match="Evidence does not match"):
        apply_git_proposal(output, root, "README.md", check=True)


def test_suggest_cli_passes_evidence_policy(tmp_path):
    from unittest.mock import patch

    from docguard.ai.config import AIConfig
    from docguard.cli import main

    with (
        patch("docguard.cli.load_config", return_value=AIConfig("groq", "test", "")),
        patch("docguard.cli.suggest_git", return_value=1) as suggest,
    ):
        assert (
            main(
                [
                    "suggest-git",
                    "--root",
                    str(tmp_path),
                    "--base",
                    "HEAD~1",
                    "--output",
                    str(tmp_path / "out.json"),
                    "--dry-run",
                    "--evidence-policy",
                    "direct",
                ]
            )
            == 0
        )
    assert suggest.call_args.kwargs["evidence_policy"] == "direct"


def test_gap_report_is_bounded_and_announces_omissions(tmp_path):
    body = "def total(x):\n" + "".join(f"    missing_{i}(x)\n" for i in range(25))
    items, gaps = collect(tmp_path, {"api.py": body})
    assert not items
    assert len(gaps) == 12
    assert gaps[-1]["reference"] == "*"
    assert "report limit" in gaps[-1]["reason"]


def test_class_seed_explains_that_method_mapping_is_needed(tmp_path):
    items, gaps = collect(
        tmp_path,
        {"api.py": "class Thing:\n    def method(self): return missing()\n"},
        "api.py:Thing",
    )
    assert not items and "specific methods" in gaps[0]["reason"]
