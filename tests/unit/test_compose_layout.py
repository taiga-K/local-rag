"""Compose layout for Windows bridge networking and named data volumes.

Principle: the file a person runs is the contract. Service DNS on the default
file, host network only on the Linux override, and the five named volumes.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class _Reset:
    def __init__(self, value):
        self.value = value


class _Loader(yaml.SafeLoader):
    pass


def _reset(loader: yaml.SafeLoader, node: yaml.nodes.SequenceNode) -> _Reset:
    return _Reset(loader.construct_sequence(node))


_Loader.add_constructor("!reset", _reset)


def _load(path: Path):
    return yaml.load(path.read_text(), Loader=_Loader)


def test_default_compose_uses_bridge_and_named_volumes():
    doc = _load(ROOT / "docker-compose.yml")
    assert doc["name"] == "kbindex"
    api = doc["services"]["api"]
    worker = doc["services"]["worker"]
    assert "network_mode" not in api
    assert "network_mode" not in worker
    assert api["ports"] == ["127.0.0.1:43123:43123"]
    assert api["environment"]["DATABASE_URL"] == "postgresql://kbindex:kbindex@postgres:5432/kbindex"
    assert api["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert api["environment"]["QDRANT_URL"] == "http://qdrant:6333"
    assert worker["environment"]["DATABASE_URL"] == api["environment"]["DATABASE_URL"]
    assert worker["environment"]["REDIS_URL"] == api["environment"]["REDIS_URL"]
    assert worker["environment"]["QDRANT_URL"] == api["environment"]["QDRANT_URL"]
    assert doc["services"]["redis"]["command"] == [
        "redis-server",
        "--appendonly",
        "yes",
        "--appendfsync",
        "everysec",
    ]
    assert doc["services"]["postgres"]["volumes"] == ["postgres_data:/var/lib/postgresql/data"]
    assert doc["services"]["redis"]["volumes"] == ["redis_data:/data"]
    assert doc["services"]["qdrant"]["volumes"] == ["qdrant_storage:/qdrant/storage"]
    assert "records:/data/records" in api["volumes"]
    assert "hf:/data/hf" in api["volumes"]
    assert set(doc["volumes"]) == {
        "postgres_data",
        "redis_data",
        "qdrant_storage",
        "records",
        "hf",
    }


def test_hostnet_override_puts_api_and_worker_on_the_host():
    doc = _load(ROOT / "docker-compose.hostnet.yml")
    api = doc["services"]["api"]
    worker = doc["services"]["worker"]
    assert api["network_mode"] == "host"
    assert worker["network_mode"] == "host"
    assert isinstance(api["ports"], _Reset)
    assert api["ports"].value == []
    assert api["environment"]["DATABASE_URL"] == "postgresql://kbindex:kbindex@127.0.0.1:54329/kbindex"
    assert api["environment"]["REDIS_URL"] == "redis://127.0.0.1:63799/0"
    assert api["environment"]["QDRANT_URL"] == "http://127.0.0.1:46333"
    assert worker["environment"] == api["environment"]
