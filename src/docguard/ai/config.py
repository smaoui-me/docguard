"""Explicit, non-mutating AI configuration. Never search parent repositories."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from docguard.ai.files import ProposalError, read_bytes

DEFAULT_MODELS = {"openai": "gpt-4.1-mini", "groq": "openai/gpt-oss-120b"}


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    api_key: str = field(repr=False)


def read_env(path: Path) -> dict[str, str]:
    """Read single-line KEY=value, quotes, and comments; no expansion/execution."""
    values: dict[str, str] = {}
    for number, line in enumerate(
        read_bytes(path, 65536).decode("utf-8-sig").splitlines(), 1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if match is None:
            raise ProposalError(f"Invalid .env assignment at line {number}")
        key, value = match.groups()
        if key in values:
            raise ProposalError(f"Duplicate .env assignment at line {number}")
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (
                value[end + 1 :].strip()
                and not value[end + 1 :].strip().startswith("#")
            ):
                raise ProposalError(f"Invalid .env quoting at line {number}")
            value = value[1:end]
        else:
            value = (
                ""
                if value.startswith("#")
                else re.split(r"\s+#", value, maxsplit=1)[0].strip()
            )
        values[key] = value
    return values


def load_config(
    env_file: Path | None = None, provider: str | None = None, model: str | None = None
) -> AIConfig:
    path = env_file if env_file is not None else Path.cwd() / ".env"
    values = read_env(path) if env_file is not None or path.exists() else {}
    values.update(os.environ)
    chosen = (
        provider
        if provider is not None
        else values.get("DOCGUARD_AI_PROVIDER", "openai")
    )
    if chosen not in DEFAULT_MODELS:
        raise ProposalError("AI provider must be openai or groq")
    chosen_model = (
        model
        if model is not None
        else values.get("DOCGUARD_MODEL", DEFAULT_MODELS[chosen])
    )
    if not chosen_model.strip():
        raise ProposalError("DOCGUARD_MODEL must not be empty")
    return AIConfig(chosen, chosen_model, values.get(f"{chosen.upper()}_API_KEY", ""))
