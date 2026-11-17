"""Process settings. Parsed once at the boundary."""

from __future__ import annotations

import hashlib
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
    tokenizers: tuple[str, ...]
    sudachi_mode: str
    sudachi_normalize: bool
    fusion_method: str
    fusion_k: int
    bm25_k1: float
    bm25_b: float
    api_port: int

    @property
    def fingerprint(self) -> str:
        lines = [
            self.model,
            self.backend,
            "B",
            ",".join(sorted(self.tokenizers)),
            self.sudachi_mode,
            str(self.sudachi_normalize).lower(),
            self.fusion_method,
            str(self.fusion_k),
            "検索文書: ",
            "検索クエリ: ",
        ]
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def load_settings(path: str | None = None) -> Settings:
    raw: dict = {}
    config_path = path or os.environ.get("KBINDEX_CONFIG", "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    embedding = raw.get("embedding") or {}
    keyword = raw.get("keyword") or {}
    sudachi = keyword.get("sudachi") or {}
    fusion = raw.get("fusion") or {}
    bm25 = raw.get("bm25") or {}
    method = str(fusion.get("method", "rrf"))
    if method != "rrf":
        raise SystemExit(f"fusion.method {method} is not implemented")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://kbindex:kbindex@127.0.0.1:54329/kbindex"),
        redis_url=os.environ.get("REDIS_URL", "redis://127.0.0.1:63799/0"),
        qdrant_url=os.environ.get("QDRANT_URL", "http://127.0.0.1:46333"),
        data_dir=os.environ.get("DATA_DIR", "/data/records"),
        model=str(embedding.get("model", "cl-nagoya/ruri-v3-310m")),
        device=str(embedding.get("device", "cpu")),
        backend=str(embedding.get("backend", os.environ.get("EMBED_BACKEND", "sentence-transformers"))),
        tokenizers=tuple(keyword.get("tokenizers") or ["sudachi", "char_bigram"]),
        sudachi_mode=str(sudachi.get("mode", "C")),
        sudachi_normalize=bool(sudachi.get("normalize", True)),
        fusion_method=method,
        fusion_k=int(fusion.get("k", 60)),
        bm25_k1=float(bm25.get("k1", 1.2)),
        bm25_b=float(bm25.get("b", 0.75)),
        api_port=int(os.environ.get("PORT", "43123")),
    )
