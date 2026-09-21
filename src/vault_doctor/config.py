"""配置加载：config.local.toml（已 gitignore）与环境变量。

优先级：--config 指定文件 > 环境变量 > 当前目录 config.local.toml。
api_key 绝不入库：仓库里只有 config.example.toml 模板。
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel


class LLMConfig(BaseModel):
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    api_key: str
    model: str = "glm-4-flash"
    timeout_seconds: float = 60.0
    max_session_tokens: int | None = None


class ConfigError(RuntimeError):
    pass


def load_llm_config(path: Path | None = None) -> LLMConfig:
    """加载 LLM 配置；找不到任何来源时抛 ConfigError（附带创建指引）。"""
    if path is not None:
        if not path.is_file():
            raise ConfigError(f"配置文件不存在：{path}")
        return _from_toml(path)

    env_key = os.environ.get("VAULT_DOCTOR_API_KEY")
    if env_key:
        fields = LLMConfig.model_fields
        return LLMConfig(
            base_url=os.environ.get("VAULT_DOCTOR_BASE_URL", fields["base_url"].default),
            api_key=env_key,
            model=os.environ.get("VAULT_DOCTOR_MODEL", fields["model"].default),
        )

    local = Path("config.local.toml")
    if local.is_file():
        return _from_toml(local)

    raise ConfigError(
        "未找到 LLM 配置。三选一：\n"
        "  1) 复制 config.example.toml 为 config.local.toml 并填入 api_key（该文件已 gitignore）\n"
        "  2) 设置环境变量 VAULT_DOCTOR_API_KEY（可选 VAULT_DOCTOR_BASE_URL / VAULT_DOCTOR_MODEL）\n"
        "  3) 用 --config 指定配置文件路径"
    )


def _from_toml(path: Path) -> LLMConfig:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"配置文件格式错误：{exc}") from exc
    section = data.get("llm")
    if not isinstance(section, dict) or "api_key" not in section:
        raise ConfigError(f"{path} 缺少 [llm] 表或 llm.api_key 字段")
    fields = LLMConfig.model_fields
    return LLMConfig(**{k: section[k] for k in fields if k in section})
