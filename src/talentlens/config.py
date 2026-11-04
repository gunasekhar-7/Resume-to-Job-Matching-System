"""Central configuration.

Two layers:
1. ``configs/default.yaml`` holds behaviour-tuning parameters (weights, limits).
2. Environment variables (``TALENTLENS_*``) hold deployment-specific values and
   secrets, and may override a small set of YAML values.

Nothing in this module reads secrets from disk beyond ``.env`` (via pydantic-settings).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(os.environ.get("TALENTLENS_ROOT", Path(__file__).resolve().parents[2])).resolve()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"


class EnvSettings(BaseSettings):
    """Deployment settings sourced from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_prefix="TALENTLENS_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    config_path: str = str(DEFAULT_CONFIG_PATH)
    log_level: str = "INFO"

    database_url: str = "sqlite:///./artifacts/talentlens.db"
    artifacts_dir: str = "artifacts"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"
    frontend_api_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:8501"
    rate_limit_per_minute: int = 60

    embedding_backend: str | None = None
    embedding_model: str | None = None
    reranker_enabled: bool | None = None
    resume_retention_hours: int | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_env_settings() -> EnvSettings:
    return EnvSettings()


class Config:
    """Read-only accessor for the YAML configuration tree."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self._data = data
        self.path = path
        self.project_root = PROJECT_ROOT

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        config_path = Path(path or os.environ.get("TALENTLENS_CONFIG") or DEFAULT_CONFIG_PATH)
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        config = cls(data, config_path)
        config._apply_env_overrides()
        config.validate()
        return config

    def _apply_env_overrides(self) -> None:
        env = get_env_settings()
        if env.embedding_backend:
            self._data.setdefault("embeddings", {})["backend"] = env.embedding_backend
        if env.embedding_model:
            self._data.setdefault("embeddings", {})["model_name"] = env.embedding_model
        if env.reranker_enabled is not None:
            self._data.setdefault("matching", {}).setdefault("reranker", {})["enabled"] = env.reranker_enabled
        if env.resume_retention_hours is not None:
            self._data.setdefault("privacy", {})["resume_retention_hours"] = env.resume_retention_hours
        if env.rate_limit_per_minute:
            self._data.setdefault("api", {})["rate_limit_per_minute"] = env.rate_limit_per_minute

    def validate(self) -> None:
        weights = self.get("matching.weights", {}) or {}
        required = {"semantic", "section_relevance", "required_skills", "preferred_skills", "experience"}
        missing = required - set(weights)
        if missing:
            raise ValueError(f"matching.weights is missing components: {sorted(missing)}")
        total = sum(float(value) for value in weights.values())
        if not 0.99 <= total <= 1.01:
            raise ValueError(f"matching.weights must sum to 1.0 (got {total:.4f})")
        if not self.get("api.page_size_default", 20) <= self.get("api.page_size_max", 100):
            raise ValueError("api.page_size_default must not exceed api.page_size_max")

    # ------------------------------------------------------------------ access
    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self._data.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def weights(self) -> dict[str, float]:
        return {key: float(value) for key, value in (self.get("matching.weights") or {}).items()}

    @property
    def config_version(self) -> str:
        return str(self.get("project.config_version", "unknown"))

    @property
    def project_version(self) -> str:
        return str(self.get("project.version", "0.0.0"))

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.get("paths.data_dir", "data"))

    def resolve(self, relative: str | Path) -> Path:
        path = Path(relative)
        return path if path.is_absolute() else (self.project_root / path)

    @property
    def artifacts_dir(self) -> Path:
        return self.resolve(self.get("paths.artifacts_dir", "artifacts"))

    @property
    def reports_dir(self) -> Path:
        return self.resolve(self.get("paths.reports_dir", "reports"))

    def ensure_directories(self) -> None:
        for key in ("data_dir", "raw_dir", "processed_dir", "annotations_dir", "sample_dir", "artifacts_dir", "reports_dir"):
            value = self.get(f"paths.{key}")
            if value:
                self.resolve(value).mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict[str, Any]:
        """Non-secret configuration summary used in API responses and logs."""
        return {
            "config_version": self.config_version,
            "project_version": self.project_version,
            "embedding_backend": self.get("embeddings.backend"),
            "embedding_model": self.get("embeddings.model_name"),
            "reranker_enabled": self.get("matching.reranker.enabled"),
            "weights": self.weights,
            "faiss_index_type": self.get("retrieval.faiss.index_type"),
        }


@lru_cache(maxsize=1)
def get_config() -> Config:
    config = Config.load()
    config.ensure_directories()
    return config


def reload_config() -> Config:
    """Clear the cache (used by tests and by long-running processes after a config change)."""
    get_config.cache_clear()
    return get_config()
