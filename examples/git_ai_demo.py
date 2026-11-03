"""Create a disposable two-commit repository for suggest-git. No AI requests."""

import argparse
from pathlib import Path

from docguard.ai.dataset import create_case_repository, load_cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".docguard-demo-git"))
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output exists; choose a new demo directory")
    cases = load_cases(
        Path(__file__).resolve().parents[1] / "evaluations/git_cases.toml"
    )
    case = next(item for item in cases if item["id"] == "timeout_parameter")
    base, head = create_case_repository(case, args.output)
    print(f"Created {args.output}; base={base}; head={head}. No AI calls.")
    print("Use --base HEAD~1 --head HEAD with suggest-git.")


if __name__ == "__main__":
    main()
