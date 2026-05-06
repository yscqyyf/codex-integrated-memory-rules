from __future__ import annotations

import json
import os
from pathlib import Path
import tomllib


DEFAULT_RUNTIME_CONFIG_TEMPLATE = """[openai_compatible]
# model = "gpt-4.1"
# base_url = "https://api.openai.com/v1"
# wire_api = "chat_completions"
# api_key_env = "OPENAI_API_KEY"
# api_key = ""
"""


def candidate_config_paths(root: str | Path | None = None) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()

    def add_path(path: str | Path | None) -> None:
        if not path:
            return
        candidate = Path(path).expanduser()
        try:
            normalized = candidate.resolve(strict=False)
        except OSError:
            normalized = candidate
        if normalized in seen:
            return
        seen.add(normalized)
        paths.append(normalized)

    env_path = os.environ.get("PRUNE_MEM_CONFIG")
    add_path(env_path)
    if root:
        add_path(Path(root) / "config.local.toml")
    else:
        add_path(Path.cwd() / "config.local.toml")
    return paths


def load_runtime_config(root: str | Path | None = None) -> dict:
    for path in candidate_config_paths(root):
        if path.exists():
            return tomllib.loads(path.read_text(encoding="utf-8"))
    return {}


def preferred_runtime_config_path(root: str | Path | None = None) -> Path:
    paths = candidate_config_paths(root)
    for path in paths:
        if path.name == "config.local.toml":
            return path
    return Path.cwd() / "config.local.toml"


def ensure_runtime_config_template(root: str | Path | None = None) -> Path:
    path = preferred_runtime_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_RUNTIME_CONFIG_TEMPLATE, encoding="utf-8")
    return path


def save_runtime_model_config(
    root: str | Path | None,
    *,
    model: str,
    base_url: str,
    wire_api: str,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> Path:
    path = preferred_runtime_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[openai_compatible]",
        f'model = "{model}"',
        f'base_url = "{base_url}"',
        f'wire_api = "{wire_api}"',
    ]
    if api_key:
        lines.append(f'api_key = "{api_key}"')
    elif api_key_env:
        lines.append(f'api_key_env = "{api_key_env}"')
    else:
        lines.append('api_key_env = "OPENAI_API_KEY"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def resolve_backend_value(root: str | Path | None, section: str, key: str, fallback: str | None = None) -> str | None:
    config = load_runtime_config(root)
    return config.get(section, {}).get(key, fallback)


def codex_root() -> Path:
    return Path.home() / ".codex"


def load_codex_config() -> dict:
    path = codex_root() / "config.toml"
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_codex_auth() -> dict:
    path = codex_root() / "auth.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_codex_model_config() -> dict:
    config = load_codex_config()
    auth = load_codex_auth()

    provider_name = config.get("model_provider")
    model = config.get("model")
    provider = config.get("model_providers", {}).get(provider_name, {}) if provider_name else {}

    return {
        "provider_name": provider_name,
        "model": model,
        "base_url": provider.get("base_url"),
        "wire_api": provider.get("wire_api"),
        "requires_openai_auth": provider.get("requires_openai_auth", False),
        "api_key": auth.get("OPENAI_API_KEY"),
    }


def diagnose_runtime(root: str | Path | None = None) -> dict:
    config_paths = candidate_config_paths(root)
    loaded_config_path = None
    loaded_config = {}
    for path in config_paths:
        if path.exists():
            loaded_config_path = path
            loaded_config = tomllib.loads(path.read_text(encoding="utf-8"))
            break

    local_section = loaded_config.get("openai_compatible", {})
    codex = resolve_codex_model_config()

    api_key_env = local_section.get("api_key_env", "OPENAI_API_KEY")
    env_key_present = bool(os.environ.get(api_key_env))
    local_key_present = bool(local_section.get("api_key"))

    model = local_section.get("model") or codex.get("model")
    base_url = local_section.get("base_url") or codex.get("base_url")
    wire_api = local_section.get("wire_api") or codex.get("wire_api")
    api_key_source = None
    if local_key_present:
        api_key_source = "config.local.toml"
    elif env_key_present:
        api_key_source = f"env:{api_key_env}"
    elif codex.get("api_key"):
        api_key_source = "~/.codex/auth.json"

    openai_ready = bool(model and base_url and api_key_source)
    auto_backend = "openai-compatible" if openai_ready else "heuristic"

    missing = []
    if not model:
        missing.append("model")
    if not base_url:
        missing.append("base_url")
    if not api_key_source:
        missing.append("api_key")

    return {
        "config_search_paths": [str(path) for path in config_paths],
        "loaded_config_path": str(loaded_config_path) if loaded_config_path else None,
        "local_config_present": loaded_config_path is not None,
        "local_openai_section": {
            "model": local_section.get("model"),
            "base_url": local_section.get("base_url"),
            "wire_api": local_section.get("wire_api"),
            "api_key_env": local_section.get("api_key_env"),
            "api_key_present": local_key_present,
        },
        "codex_model_config": {
            "provider_name": codex.get("provider_name"),
            "model": codex.get("model"),
            "base_url": codex.get("base_url"),
            "wire_api": codex.get("wire_api"),
            "requires_openai_auth": codex.get("requires_openai_auth"),
            "api_key_present": bool(codex.get("api_key")),
        },
        "resolved": {
            "model": model,
            "base_url": base_url,
            "wire_api": wire_api,
            "api_key_source": api_key_source,
            "auto_backend": auto_backend,
            "missing": missing,
        },
    }
