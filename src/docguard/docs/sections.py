"""Conservative ATX Markdown section selection with exact UTF-8 byte boundaries."""

import re
from dataclasses import dataclass

from docguard.ai.files import ProposalError


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]
    start: int
    end: int

    def text(self, raw: bytes) -> str:
        return raw[self.start : self.end].decode("utf-8")


def sections(raw: bytes) -> tuple[Section, ...]:
    """Support ATX headings and fenced code; fail closed on unsupported structure.

    This is intentionally not a general Markdown renderer. HTML blocks, Setext
    headings and indented code are rejected to avoid guessing section boundaries.
    """
    raw.decode("utf-8")
    headings: list[tuple[int, str, int]] = []
    offset = 0
    fence = b""
    for line in raw.splitlines(keepends=True):
        body = line.rstrip(b"\r\n")
        if offset == 0:
            body = body.removeprefix(b"\xef\xbb\xbf")
        marker = re.match(rb" {0,3}(`{3,}|~{3,})(.*)$", body)
        if fence:
            if (
                marker
                and marker[1][:1] == fence[:1]
                and len(marker[1]) >= len(fence)
                and not marker[2].strip()
            ):
                fence = b""
        elif marker:
            if marker[1].startswith(b"`") and b"`" in marker[2]:
                raise ProposalError("Unsupported Markdown fence")
            fence = marker[1]
        else:
            if re.fullmatch(rb" {0,3}#{1,6}[ \t]*", body) or re.match(
                rb" {1,3}#{1,6}(?:[ \t]|$)", body
            ):
                raise ProposalError(
                    "Empty or indented Markdown headings are unsupported for section edits"
                )
            if (
                (body.startswith((b"    ", b"\t")) and body.strip())
                or b"<" in body
                or re.fullmatch(rb" {0,3}(?:=+|-+)\s*", body)
            ):
                raise ProposalError(
                    "Section edits require ATX Markdown without HTML, Setext headings or indented code"
                )
            heading = re.fullmatch(rb" {0,3}(#{1,6})[ \t]+(.+?)\s*", body)
            if heading:
                label = (heading[1] + b" " + heading[2]).decode("utf-8")
                headings.append((len(heading[1]), label, offset))
        offset += len(line)
    if fence:
        raise ProposalError("Unclosed Markdown fence")
    result = []
    parents: list[tuple[int, str]] = []
    for index, (level, label, start) in enumerate(headings):
        while parents and parents[-1][0] >= level:
            parents.pop()
        parents.append((level, label))
        end = next(
            (pos for depth, _, pos in headings[index + 1 :] if depth <= level), len(raw)
        )
        result.append(Section(tuple(title for _, title in parents), start, end))
    return tuple(result)


def select_section(raw: bytes, path: tuple[str, ...]) -> Section:
    matches = [item for item in sections(raw) if item.path == path]
    if len(matches) != 1:
        raise ProposalError("Section heading path is missing or ambiguous")
    return matches[0]


def replace_section(raw: bytes, path: tuple[str, ...], replacement: str) -> bytes:
    selected = select_section(raw, path)
    value = replacement.encode("utf-8")
    if len(replacement) > 60000:
        raise ProposalError("Proposed section exceeds 60000 characters")
    parsed = sections(value)
    level = len(path[-1].split(" ", 1)[0])
    if (
        not parsed
        or parsed[0].start != 0
        or parsed[0].path != (path[-1],)
        or any(len(item.path) == 1 for item in parsed[1:])
    ):
        raise ProposalError(
            "Replacement must retain the section heading and stay inside it"
        )
    if any(len(item.path[-1].split(" ", 1)[0]) <= level for item in parsed[1:]):
        raise ProposalError("Replacement contains a heading outside its scope")
    if selected.end < len(raw) and not value.endswith(b"\n"):
        raise ProposalError(
            "Section replacement must preserve the following heading boundary"
        )
    result = raw[: selected.start] + value + raw[selected.end :]
    if len(result) > 1_000_000:
        raise ProposalError("Proposed document exceeds 1 MB")
    # Validate the assembled document, including its boundary with the next section.
    final = select_section(result, path)
    if final.start != selected.start or final.end != selected.start + len(value):
        raise ProposalError("Replacement changes Markdown section boundaries")
    return result


def validate_section_edit(original: str, content: str, path: tuple[str, ...]) -> None:
    old, new = original.encode("utf-8"), content.encode("utf-8")
    target = select_section(new, path)
    if replace_section(old, path, target.text(new)) != new:
        raise ProposalError("Proposal changes bytes outside the mapped section")
