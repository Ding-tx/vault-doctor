"""M1-C 配置加载测试：三来源优先级与错误指引。"""
from pathlib import Path

import pytest

from vault_doctor.config import ConfigError, load_llm_config


def _write_cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.local.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_from_toml(tmp_path: Path):
    p = _write_cfg(tmp_path, '[llm]\napi_key = "sk-test"\nmodel = "glm-4.7"\n')
    cfg = load_llm_config(p)
    assert cfg.api_key == "sk-test"
    assert cfg.model == "glm-4.7"
    assert cfg.base_url == "https://open.bigmodel.cn/api/paas/v4"


def test_env_overrides_local_file(monkeypatch):
    monkeypatch.setenv("VAULT_DOCTOR_API_KEY", "env-key")
    cfg = load_llm_config(None)
    assert cfg.api_key == "env-key"


def test_missing_config_raises_with_guide(monkeypatch):
    monkeypatch.delenv("VAULT_DOCTOR_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="config.local.toml"):
        load_llm_config(None)


def test_toml_without_api_key(tmp_path: Path):
    p = _write_cfg(tmp_path, '[llm]\nmodel = "x"\n')
    with pytest.raises(ConfigError, match="api_key"):
        load_llm_config(p)
