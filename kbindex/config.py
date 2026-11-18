"""Process settings. Parsed once at the boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    qdrant_url: str
    data_dir: str
    model: str
    device: str
    backend: str
    api_port: int
    redis_lanes: int = 1


def load_settings(path: str | None = None) -> Settings:
    raw: dict = {}
    config_path = path or os.environ.get("KBINDEX_CONFIG", "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise SystemExit("config root must be a mapping")
        raw = loaded
    embedding = raw.get("embedding") or {}
    device = str(embedding.get("device", "cpu"))
    if device not in {"cpu", "cuda"}:
        raise SystemExit("embedding.device must be cpu or cuda")
    backend = str(embedding.get("backend", os.environ.get("EMBED_BACKEND", "sentence-transformers")))
    if backend not in {"sentence-transformers", "fake"}:
        raise SystemExit("embedding.backend must be sentence-transformers or fake")
    redis_cfg = raw.get("redis") or {}
    lanes = redis_cfg.get("lanes", 1)
    if isinstance(lanes, bool) or not isinstance(lanes, int) or not 1 <= lanes <= 64:
        raise SystemExit("redis.lanes must be an integer from 1 to 64")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://kbindex:kbindex@127.0.0.1:54329/kbindex"),
        redis_url=os.environ.get("REDIS_URL", "redis://127.0.0.1:63799/0"),
        qdrant_url=os.environ.get("QDRANT_URL", "http://127.0.0.1:46333"),
        data_dir=os.environ.get("DATA_DIR", "/data/records"),
        model=str(embedding.get("model", "cl-nagoya/ruri-v3-310m")),
        device=device,
        backend=backend,
        api_port=int(os.environ.get("PORT", "43123")),
        redis_lanes=lanes,
    )


def rebuild_enabled() -> bool:
    """PipesHub's ENABLE_VECTOR_STORE_REBUILD. Default off."""
    raw = os.environ.get("ENABLE_VECTOR_STORE_REBUILD", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}
