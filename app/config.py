from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', env_file_encoding='utf-8', extra='ignore')
    llm_mode: Literal['fixture', 'live'] = 'fixture'
    llm_base_url: str = ''
    llm_model: str = ''
    llm_api_key: SecretStr = SecretStr('')
    llm_json_mode: bool = True
    llm_disable_thinking: bool = False
    llm_max_tokens: int = Field(default=4096, ge=512, le=8192)
    # Accept the legacy .env field; live responses report the actual prompt constant.
    prompt_version: Literal['v1', 'v2-card', 'v3-card', 'v4-card', 'v5-card', 'v6-card', 'v7-card', 'v8-card', 'v9-card', 'v10-card', 'v11-card'] = 'v11-card'
    enable_image_input: bool = False
