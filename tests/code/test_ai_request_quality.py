import copy
import json

import pytest

from docguard.ai.preservation import inspect_preservation
from docguard.ai.provider import compact_context, request_payload


def test_compaction_retains_evidence_and_nonduplicate_source_without_mutating_input():
    context = {
        "document_text": "Hello\n",
        "previous_document_text": "Hello\n",
        "evidence": [{"id": "after:a.py:f", "text": "def f(): pass"}],
        "entities": [
            {
                "entity_id": "a.py:f",
                "current_source": "def f(): pass",
                "after": {"decorators": ["cache"]},
            },
            {"entity_id": "a.py:g", "current_source": "def g(): pass"},
            {"entity_id": "a.py:removed", "current_source": None},
        ],
        "evidence_gaps": [{"reason": "unresolved dependency"}],
        "changes": [{"diff": "-old\n+new"}],
    }
    saved = copy.deepcopy(context)
    compact = compact_context(context)
    assert context == saved
    assert compact["evidence"] == context["evidence"]
    assert compact["entities"][0] == {
        "entity_id": "a.py:f",
        "current_source_evidence_id": "after:a.py:f",
        "after": {"decorators": ["cache"]},
    }
    assert compact["entities"][1:] == context["entities"][1:]
    assert compact["evidence_gaps"] == context["evidence_gaps"]
    assert compact["changes"] == context["changes"]
    assert compact["previous_document_same_as_current"] is True
    assert "previous_document_text" not in compact
    assert compact_context(compact) == compact


def test_snapshot_and_changed_historical_document_are_not_removed():
    snapshot = {"document_text": "text", "entities": [{"current_source": "source"}]}
    assert compact_context(snapshot) == snapshot
    git = {"evidence": [], "document_text": "new", "previous_document_text": "old"}
    assert compact_context(git) == git


@pytest.mark.parametrize(
    "provider,field",
    [("groq", "max_completion_tokens"), ("openai", "max_output_tokens")],
)
@pytest.mark.parametrize(
    "document,expected", [("", 2048), ("abc", 2051), ("é", 2050), ("x" * 20000, 12000)]
)
def test_output_budget_is_bounded_and_preserves_document(
    provider, field, document, expected
):
    payload = request_payload("test", {"document_text": document}, provider)
    assert payload[field] == expected
    content = (
        payload["input"] if provider == "openai" else payload["messages"][1]["content"]
    )
    assert json.loads(content)["document_text"] == document


@pytest.mark.parametrize(
    "before,after,issues",
    [
        ("Price is 1.\n\n", "Price is 2.\n\n", []),
        ("Price is 1.\r\n", "Price is 2.\n", []),
        ("Keep as-is.\n", "Keep as‑is.\n", ["surface_only_edit"]),
        ("A\n\n", "A\n", ["trailing_newlines_changed"]),
        ("A", "A\n", ["trailing_newlines_changed"]),
        (
            "See method.\n",
            "See :meth:`Option.get_default`.\n",
            ["new_references_require_review"],
        ),
        ("See [A](old).\n", "See [A](new).\n", ["new_references_require_review"]),
        ("See [A](same). 1\n", "See [A](same). 2\n", []),
        ("", "", []),
    ],
)
def test_preservation_diagnostics(before, after, issues):
    result = inspect_preservation(before, after)
    assert result["issues"] == issues
    assert result["flagged"] == bool(issues)
