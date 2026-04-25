import os
from pathlib import Path

from prune_mem.runtime_config import candidate_config_paths


def test_candidate_config_paths_dedupes_env_and_root(tmp_path, monkeypatch):
    config_path = tmp_path / "config.local.toml"
    monkeypatch.setenv("PRUNE_MEM_CONFIG", str(config_path))

    paths = candidate_config_paths(tmp_path)

    assert paths == [config_path.resolve()]


def test_candidate_config_paths_skips_cwd_when_root_is_provided(tmp_path, monkeypatch):
    monkeypatch.delenv("PRUNE_MEM_CONFIG", raising=False)
    paths = candidate_config_paths(tmp_path)

    assert paths == [(tmp_path / "config.local.toml").resolve()]


def test_candidate_config_paths_uses_cwd_without_root(tmp_path, monkeypatch):
    monkeypatch.delenv("PRUNE_MEM_CONFIG", raising=False)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        paths = candidate_config_paths()
    finally:
        os.chdir(old_cwd)

    assert paths == [(tmp_path / "config.local.toml").resolve()]
