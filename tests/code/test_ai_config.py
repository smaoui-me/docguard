import os
from unittest.mock import patch

import pytest

from docguard.ai.config import load_config, read_env
from docguard.ai.files import ProposalError


def test_file_environment_and_cli_precedence(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        '# ignored\nDOCGUARD_AI_PROVIDER=groq\nDOCGUARD_MODEL="openai/gpt-oss-120b" # comment\nGROQ_API_KEY=secret-value\nOPENAI_API_KEY=other-secret\n',
        encoding="utf-8",
    )
    with patch.dict(os.environ, {}, clear=True):
        config = load_config(env)
        assert config.provider == "groq"
        assert config.model == "openai/gpt-oss-120b"
        assert config.api_key == "secret-value"
        assert "secret-value" not in repr(config)
        assert "GROQ_API_KEY" not in os.environ
        with patch.dict(
            os.environ, {"DOCGUARD_MODEL": "env-model", "GROQ_API_KEY": "env-key"}
        ):
            assert load_config(env).model == "env-model"
            assert load_config(env).api_key == "env-key"
            assert load_config(env, "openai", "cli-model").api_key == "other-secret"
            assert load_config(env, model="cli-model").model == "cli-model"
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            assert load_config(env).api_key == ""


def test_default_file_only_current_directory_and_no_expansion(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GROQ_API_KEY=parent-secret", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    with patch.dict(os.environ, {}, clear=True):
        assert load_config().provider == "openai"
        assert load_config(provider="groq").model == "openai/gpt-oss-120b"
        assert load_config(provider="groq").api_key == ""
        (child / ".env").write_text(
            "DOCGUARD_AI_PROVIDER=groq\nGROQ_API_KEY='$(echo secret)#literal'",
            encoding="utf-8",
        )
        assert load_config().api_key == "$(echo secret)#literal"


@pytest.mark.parametrize(
    "content",
    [
        "secret-without-equals",
        'KEY="secret',
        "KEY=one\nKEY=secret",
        'KEY="secret" trailing',
        "=secret",
    ],
)
def test_invalid_env_never_echoes_values(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProposalError) as error:
        read_env(path)
    assert "secret" not in str(error.value)


def test_empty_value_with_inline_comment(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "GROQ_API_KEY= # add a key here\nDOCGUARD_AI_PROVIDER=groq", encoding="utf-8"
    )
    assert read_env(path)["GROQ_API_KEY"] == ""


def test_invalid_provider_empty_model_and_missing_file(tmp_path):
    path = tmp_path / ".env"
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(FileNotFoundError):
            load_config(path)
        path.write_text("DOCGUARD_AI_PROVIDER=unknown", encoding="utf-8")
        with pytest.raises(ProposalError, match="provider"):
            load_config(path)
        path.write_text("DOCGUARD_MODEL=", encoding="utf-8")
        with pytest.raises(ProposalError, match="MODEL"):
            load_config(path)
