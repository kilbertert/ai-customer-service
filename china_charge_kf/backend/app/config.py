from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_cors_origins: str = "http://localhost:5173"
    port: int = 8011

    coze_api_base: str = "https://api.coze.cn"
    coze_api_token: str
    coze_workflow_id: str

    coze_param_text: str = "input_text"
    coze_param_image_id: str = "input_img_id"
    coze_param_audio_id: str = "input_audio_id"
    coze_param_language: str = "language"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",") if o.strip()]


settings = Settings()

