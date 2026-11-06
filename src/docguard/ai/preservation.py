"""Conservative edit diagnostics, not a substitute for semantic human review."""

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

PRESERVATION_VERSION = 1


def inspect_preservation(original: str, proposed: str) -> dict[str, object]:
    """Flag surface-only churn and newly introduced references without rejecting edits.

    Semantic rewrites (including unnecessary ones) can pass these checks. Findings
    are review signals, not proof of incorrectness. Normalize CRLF for comparison.
    """
    before = original.replace("\r\n", "\n")
    after = proposed.replace("\r\n", "\n")
    issues: list[str] = []
    if len(before) - len(before.rstrip("\n")) != len(after) - len(after.rstrip("\n")):
        issues.append("trailing_newlines_changed")

    def words(text: str) -> list[str]:
        return re.findall(r"\w+", unicodedata.normalize("NFKC", text))

    old_lines, new_lines = before.splitlines(), after.splitlines()
    for tag, i, j, k, end in SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    ).get_opcodes():
        if tag == "replace" and words("\n".join(old_lines[i:j])) == words(
            "\n".join(new_lines[k:end])
        ):
            issues.append("surface_only_edit")
            break
    reference = r":[a-zA-Z][\w:]*:`[^`]+`|\[[^\]\n]+\]\([^\)\n]+\)"
    added = Counter(re.findall(reference, after)) - Counter(
        re.findall(reference, before)
    )
    if added:
        issues.append("new_references_require_review")
    return {"version": PRESERVATION_VERSION, "issues": issues, "flagged": bool(issues)}
