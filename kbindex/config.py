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
    bigram_nfkc: bool = True
    bigram_casefold: bool = False
    bigram_drop_space: bool = True
    bigram_drop_control: bool = True
    bigram_drop_punct: bool = False
    redis_lanes: int = 1

    def index_fingerprint(self, *, hidden_size: int, max_seq_length: int) -> str:
        """Hash of the inputs that change vectors or postings.

        `device`, BM25 `k1`/`b`, `fusion.k`, and Redis lane count stay out.
        They do not change stored bytes. Character-bigram flags stay in,
        because they change the postings.
        """
        lines = [
            self.model,
            f"{hidden_size} {max_seq_length}",
            "B",
            ",".join(sorted(self.tokenizers)),
            f"{self.sudachi_mode} {str(self.sudachi_normalize).lower()}",
            self.fusion_method,
            "検索文書: ",
            "検索クエリ: ",
            " ".join(
                (
                    "1" if self.bigram_nfkc else "0",
                    "1" if self.bigram_casefold else "0",
                    "1" if self.bigram_drop_space else "0",
                    "1" if self.bigram_drop_control else "0",
                    "1" if self.bigram_drop_punct else "0",
                )
            ),
        ]
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()


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
    keyword = raw.get("keyword") or {}
    sudachi = keyword.get("sudachi") or {}
    fusion = raw.get("fusion") or {}
    bm25 = raw.get("bm25") or {}
    method = str(fusion.get("method", "rrf"))
    if method != "rrf":
        raise SystemExit(f"fusion.method {method} is not implemented")
    device = str(embedding.get("device", "cpu"))
    if device not in {"cpu", "cuda"}:
        raise SystemExit("embedding.device must be cpu or cuda")
    backend = str(embedding.get("backend", os.environ.get("EMBED_BACKEND", "sentence-transformers")))
    if backend not in {"sentence-transformers", "fake"}:
        raise SystemExit("embedding.backend must be sentence-transformers or fake")
    tokenizers = tuple(keyword.get("tokenizers") or ["sudachi", "char_bigram"])
    if not tokenizers or any(name not in {"sudachi", "char_bigram"} for name in tokenizers):
        raise SystemExit("keyword.tokenizers must list sudachi, char_bigram, or both")
    mode = str(sudachi.get("mode", "C"))
    if mode not in {"A", "B", "C"}:
        raise SystemExit("keyword.sudachi.mode must be A, B, or C")
    normalize = sudachi.get("normalize", True)
    if not isinstance(normalize, bool):
        raise SystemExit("keyword.sudachi.normalize must be a boolean")
    k = fusion.get("k", 60)
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise SystemExit("fusion.k must be a positive integer")
    k1 = bm25.get("k1", 1.2)
    b = bm25.get("b", 0.75)
    if isinstance(k1, bool) or not isinstance(k1, (int, float)) or float(k1) <= 0:
        raise SystemExit("bm25.k1 must be a positive number")
    if isinstance(b, bool) or not isinstance(b, (int, float)) or not 0 <= float(b) <= 1:
        raise SystemExit("bm25.b must be from 0 to 1")
    bigram = keyword.get("char_bigram") or {}
    if not isinstance(bigram, dict):
        raise SystemExit("keyword.char_bigram must be a mapping")
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
        tokenizers=tokenizers,
        sudachi_mode=mode,
        sudachi_normalize=normalize,
        fusion_method=method,
        fusion_k=k,
        bm25_k1=float(k1),
        bm25_b=float(b),
        api_port=int(os.environ.get("PORT", "43123")),
        bigram_nfkc=_flag(bigram, "nfkc", True),
        bigram_casefold=_flag(bigram, "casefold", False),
        bigram_drop_space=_flag(bigram, "drop_space", True),
        bigram_drop_control=_flag(bigram, "drop_control", True),
        bigram_drop_punct=_flag(bigram, "drop_punct", False),
        redis_lanes=lanes,
    )


def _flag(block: dict, name: str, default: bool) -> bool:
    value = block.get(name, default)
    if not isinstance(value, bool):
        raise SystemExit(f"keyword.char_bigram.{name} must be a boolean")
    return value
