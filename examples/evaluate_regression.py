"""Repeat the pinned pilot with pacing; preserve baseline and every case checkpoint.

Run from the project root. Offline by default; --live sends repository excerpts
to the configured provider. Labels and manifests must match the baseline.
"""

import argparse
import json
import time
from pathlib import Path

from docguard.ai.config import load_config
from docguard.ai.files import digest, read_bytes, write_new_json
from docguard.ai.preservation import inspect_preservation
from docguard.ai.provider import GIT_PROMPT_VERSION, PROMPT_VERSION
from docguard.ai.upstream import evaluate_pr, load_manifest, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, default=Path("evaluation-paced-live-20261105.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    baseline = json.loads(read_bytes(args.baseline, limit=100_000_000).decode("utf-8"))
    config = load_config()
    if args.output.exists():
        raise SystemExit(
            "Choose a new aggregate output; per-case checkpoints can be resumed."
        )
    if (baseline["provider"], baseline["model"]) != (config.provider, config.model):
        raise SystemExit("Baseline provider/model mismatch")
    plans = [
        (
            Path("evaluations/upstream/httpx.toml"),
            Path(".docguard-upstream/httpx-full.git"),
        ),
        (Path("evaluations/upstream/click.toml"), Path(".docguard-upstream/click.git")),
    ]
    cases = [
        (manifest, repo, case)
        for manifest, repo in plans
        for case in load_manifest(manifest)
    ]
    old_rows = {row["case"]: row for row in baseline["results"]}
    if set(old_rows) != {case["id"] for _, _, case in cases}:
        raise SystemExit("Baseline case selection mismatch")
    # Check full manifest hashes, including gold labels, before spending anything.
    baseline_reports = [
        json.loads(read_bytes(Path(p), limit=100_000_000).decode("utf-8"))
        for p in baseline["case_reports"]
    ]
    for manifest, _, case in cases:
        prior = next(
            r for r in baseline_reports if case["id"] in r["identity"]["cases"]
        )
        if prior["manifest_sha256"] != digest(read_bytes(manifest)):
            raise SystemExit(
                "Baseline manifest changed; use a separately labeled experiment"
            )
    rows, reports = [], []
    requests = 0
    last_finished = None
    stop_reason = None
    for manifest, repo, case in cases:
        if requests >= 12:
            stop_reason = "Session request budget exhausted"
            break
        output = args.output.with_name(f"{args.output.stem}-{case['id']}.json")
        if args.live and last_finished is not None:
            print("Cooling down 65s", flush=True)
            while (remaining := 65 - (time.monotonic() - last_finished)) > 0:
                time.sleep(min(remaining, 10))
        print(f"Evaluating {case['id']}", flush=True)
        report = evaluate_pr(
            config,
            repo,
            manifest,
            output,
            selected=[case["id"]],
            live=args.live,
            max_requests=min(2, 12 - requests),
            max_retries=1,
            max_retry_wait=60,
            resume=output.exists(),
        )
        last_finished = time.monotonic()
        requests += report["session_requests"]
        reports.append(str(output))
        rows.extend(report["results"])
        print(
            json.dumps(
                {
                    k: rows[-1].get(k)
                    for k in (
                        "case",
                        "status",
                        "action",
                        "automatic_pass",
                        "http_status",
                        "preservation",
                    )
                }
            ),
            flush=True,
        )
        if rows[-1].get("http_status") in {401, 403, 429}:
            stop_reason = f"Stopped on HTTP {rows[-1]['http_status']}"
            break
    seen = {row["case"] for row in rows}
    rows.extend(
        {"case": case["id"], "status": "not_run"}
        for _, _, case in cases
        if case["id"] not in seen
    )
    comparison = []
    for row in rows:
        old = old_rows[row["case"]]
        previous_preservation = None
        if old.get("action") == "revise":
            proposal = old["decision"]
            previous_preservation = inspect_preservation(
                proposal["original"], proposal["content"]
            )
        comparison.append(
            {
                "case": row["case"],
                "before_status": old["status"],
                "after_status": row["status"],
                "before_action": old.get("action"),
                "after_action": row.get("action"),
                "before_pass": old.get("automatic_pass"),
                "after_pass": row.get("automatic_pass"),
                "before_preservation": previous_preservation,
                "after_preservation": row.get("preservation"),
            }
        )
    write_new_json(
        args.output,
        {
            "schema_version": 2,
            "mode": "live" if args.live else "preparation-only",
            "provider": config.provider,
            "model": config.model,
            "prompt_version": PROMPT_VERSION,
            "git_prompt_version": GIT_PROMPT_VERSION,
            "baseline_sha256": digest(read_bytes(args.baseline, limit=100_000_000)),
            "api_requests_this_session": requests,
            "minimum_inter_case_delay_seconds": 65,
            "case_reports": reports,
            "results": rows,
            "comparison": comparison,
            "baseline_metrics": baseline["metrics"],
            "metrics": summarize(rows, len(cases)),
            "stop_reason": stop_reason,
            "note": "Single regression rerun; inspected cases are not fresh held-out data. Labels unchanged. Preservation diagnostics are heuristic, scored equally on baseline and candidate. Human acceptance pending.",
        },
    )
    print(f"Saved {args.output}; session requests={requests}", flush=True)


if __name__ == "__main__":
    main()
