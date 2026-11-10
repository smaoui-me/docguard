"""Prepare or evaluate pinned real PR cases, with baselines, pacing and checkpoints."""

import argparse
from pathlib import Path

from docguard.ai.config import load_config
from docguard.ai.pilot import run_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path(".docguard-upstream"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=65)
    parser.add_argument("--provider", choices=("groq", "openai"))
    parser.add_argument("--model")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "evaluations/upstream"
    report = run_pilot(
        load_config(provider=args.provider, model=args.model),
        [
            (source / "httpx.toml", args.cache / "httpx-full.git"),
            (source / "click.toml", args.cache / "click.git"),
            (source / "httpx_claims.toml", args.cache / "httpx-full.git"),
        ],
        args.output,
        selected=args.case,
        live=args.live,
        resume=args.resume,
        max_requests=args.max_requests,
        delay_seconds=args.delay_seconds,
        progress=lambda message: print(message, flush=True),
    )
    print(f"Report: {args.output / 'summary.md'}", flush=True)
    if args.live and any(
        row["status"] != "completed" or not row.get("automatic_pass")
        for row in report["results"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
