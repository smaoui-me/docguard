"""Frozen, inspectable real-PR evidence; no inferred human labels."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from docguard.ai.benchmark import audit_benchmark
from docguard.ai.files import (
    ProposalError,
    digest,
    parse_json,
    read_bytes,
    write_new_json,
)
from docguard.ai.git_proposals import prepare_git_documents
from docguard.ai.references import (
    load_discussions,
    provisional_action,
    review_level,
    upstream_reference,
    validate_reference,
)
from docguard.ai.upstream import load_manifest, materialize_case
from docguard.git_review import git_trees

ACTIONS = {"revise", "unchanged", "needs_review"}


def load_packet(path: Path) -> tuple[str, dict[str, Any]]:
    raw = read_bytes(path, 30_000_000)
    data = parse_json(raw.decode("utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("kind") != "docguard.review-packet"
        or data.get("schema_version") != 1
    ):
        raise ProposalError("Expected a version 1 review packet")
    cases = data.get("cases")
    if (
        not isinstance(cases, list)
        or not cases
        or any(not isinstance(c, dict) for c in cases)
    ):
        raise ProposalError("Review packet requires cases")
    if any(not isinstance(c.get("case"), str) or not c["case"] for c in cases):
        raise ProposalError("Review packet requires named cases")
    if len({c["case"] for c in cases}) != len(cases):
        raise ProposalError("Duplicate review packet cases")
    for case in cases:
        if "upstream_reference" in case:
            validate_reference(case["upstream_reference"])
        provenance = case.get("provenance")
        if (
            not isinstance(case.get("exposure"), str)
            or not isinstance(provenance, dict)
            or any(
                not isinstance(provenance.get(k), str)
                for k in (
                    "pr_url",
                    "repository_url",
                    "upstream_base",
                    "upstream_head",
                    "variant",
                    "scope",
                    "license_text",
                )
            )
            or not isinstance(provenance.get("document_selections"), dict)
            or not isinstance(provenance["document_selections"].get("head"), dict)
        ):
            raise ProposalError("Missing review provenance")
        selection = provenance["document_selections"]["head"]
        if (
            any(
                not isinstance(selection.get(k), str)
                for k in ("upstream_revision", "path")
            )
            or type(selection.get("start_line")) is not int
        ):
            raise ProposalError("Missing document selection provenance")
        if not isinstance(case.get("contexts"), dict) or not isinstance(
            case.get("context_sha256"), dict
        ):
            raise ProposalError("Missing context or context hashes")
        for policy in ("mapped", "direct"):
            context = case["contexts"].get(policy)
            if (
                not isinstance(context, dict)
                or not isinstance(context.get("document_text"), str)
                or not isinstance(context.get("evidence"), list)
            ):
                raise ProposalError("Missing document or evidence")
            if case["context_sha256"].get(policy) != digest(
                json.dumps(context, sort_keys=True).encode()
            ):
                raise ProposalError("Context hash mismatch")
    return digest(raw), data


def prepare_packet(
    plans: list[tuple[Path, Path]],
    output: Path,
    selected: list[str],
    *,
    paired_upstream: bool = False,
    discussion: Path | None = None,
) -> None:
    cases = [
        (manifest, repo, c) for manifest, repo in plans for c in load_manifest(manifest)
    ]
    ids = [c["id"] for _, _, c in cases]
    if len(ids) != len(set(ids)) or set(selected) - set(ids):
        raise ProposalError("Duplicate or unknown case selection")
    cases = [entry for entry in cases if not selected or entry[2]["id"] in selected]
    discussions = load_discussions(discussion, {c["pr_url"] for _, _, c in cases})
    if paired_upstream:
        if not selected:
            raise ProposalError(
                "Select explicit seed cases with --case for paired upstream evaluation"
            )
        pairs = []
        seen_pairs = set()
        for manifest, repo, seed in cases:
            pair_key = (
                seed["pr_url"],
                seed["base"],
                seed["head"],
                seed["document_path"],
                seed["section"],
                tuple(seed["entity_ids"]),
                tuple(seed["source_paths"]),
            )
            if pair_key in seen_pairs:
                raise ProposalError("Select only one seed per reference pair")
            seen_pairs.add(pair_key)
            if seed["variant"] not in ("base_docs", "authentic_head"):
                raise ProposalError(
                    "Pair an authentic or base-doc seed, not an authored or dependency-ablation case"
                )
            if not upstream_reference(repo, seed)["changed"]:
                raise ProposalError(
                    "Paired upstream evaluation requires a changed documentation section"
                )
            for variant in ("base_docs", "authentic_head"):
                pairs.append(
                    (
                        manifest,
                        repo,
                        {**seed, "id": seed["id"] + "__" + variant, "variant": variant},
                    )
                )
        cases = pairs
    with TemporaryDirectory(prefix="docguard-review-packet-") as directory:
        workspace = Path(directory)
        audit_benchmark([p for p, _ in plans], workspace / "split-audit.json")
        rows = []
        for _, repo, case in cases:
            root = workspace / case["id"]
            provenance = materialize_case(repo, case, root)
            commits = provenance["projection_commits"]
            assert isinstance(commits, dict)
            contexts = {}
            with git_trees(root, str(commits["base"]), str(commits["head"])) as trees:
                for policy in ("mapped", "direct"):
                    _, documents, _ = prepare_git_documents(
                        trees, "docguard-map.json", evidence_policy=policy
                    )
                    if len(documents) != 1:
                        raise ProposalError(
                            "Review packet needs exactly one impacted document per case"
                        )
                    contexts[policy] = documents[0].context
            rows.append(
                {
                    "case": case["id"],
                    "group": case.get("group", case["pr_url"]),
                    "declared_split": case.get("split", "development"),
                    "exposure": "previously_inspected_regression",
                    "provenance": provenance,
                    "upstream_reference": upstream_reference(repo, case),
                    "discussion": discussions.get(case["pr_url"], []),
                    "contexts": contexts,
                    "context_sha256": {
                        k: digest(json.dumps(v, sort_keys=True).encode())
                        for k, v in contexts.items()
                    },
                }
            )
    write_new_json(
        output,
        {
            "schema_version": 1,
            "kind": "docguard.review-packet",
            "cases": rows,
            "note": "Upstream references and discussion are separate from model contexts. Prior pilot cases are regression data. Selected files only; direct retrieval cannot recover files excluded by the manifest.",
        },
    )


def load_labels(
    path: Path, packet_hash: str, packet: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    raw = read_bytes(path)
    data = parse_json(raw.decode("utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("kind") != "docguard.experiment-labels"
        or data.get("packet_sha256") != packet_hash
    ):
        raise ProposalError("Labels must match the exact review packet")
    rows = data.get("labels")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ProposalError("Invalid labels")
    expected = {c["case"] for c in packet["cases"]}
    if (
        any(not isinstance(r.get("case"), str) for r in rows)
        or len(rows) != len(expected)
        or {r.get("case") for r in rows} != expected
    ):
        raise ProposalError(
            "Label every case exactly once before running an experiment"
        )
    for row in rows:
        level = review_level(row)
        if level == "upstream_reference":
            case = next(c for c in packet["cases"] if c["case"] == row["case"])
            action = provisional_action(case)
            if (
                row.get("mapped") != action
                or row.get("direct") != action
                or row.get("reviewer") != ""
            ):
                raise ProposalError(
                    "Unreviewed reference labels must match the documented variant; supply a human review to override"
                )
        if (
            any(
                not isinstance(row.get(k), str) or row[k] not in ACTIONS
                for k in ("mapped", "direct")
            )
            or not isinstance(row.get("reviewer"), str)
            or (level != "upstream_reference" and not row["reviewer"].strip())
            or not isinstance(row.get("notes"), str)
            or not row["notes"].strip()
            or type(row.get("independent")) is not bool
        ):
            raise ProposalError(
                "Labels require reviewer, rationale, both evidence decisions and independence attestation"
            )
    return digest(raw), {r["case"]: r for r in rows}


def reference_labels(packet_path: Path, output: Path) -> None:
    packet_hash, packet = load_packet(packet_path)
    rows = []
    for case in packet["cases"]:
        action = provisional_action(case)
        rows.append(
            {
                "case": case["case"],
                "mapped": action,
                "direct": action,
                "reviewer": "",
                "independent": False,
                "review_level": "upstream_reference",
                "notes": "Provisional expectation derived from an upstream documentation change and the input variant. Relevance, correctness and evidence sufficiency have not been human-verified; no independent review implied.",
            }
        )
    write_new_json(
        output,
        {
            "schema_version": 1,
            "kind": "docguard.experiment-labels",
            "packet_sha256": packet_hash,
            "labels": rows,
        },
    )
