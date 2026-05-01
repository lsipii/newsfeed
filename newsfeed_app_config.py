import json
import os
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional

import platformdirs

from app.news_types import NewsAppConfig

_TEMPLATE_FILE = "config.default.json"
_USER_CONFIG_FILE = "config.json"
_UI_STATE_FILE = "ui_state.json"
_PACKAGED_CONFIG_PACKAGE = "newsfeed_config"
# Written on first seed so we do not reuse ~/.config/newsfeed (etc.) created by another program.
_CONFIG_DIR_MARKER_NAME = ".newsfeed-dir"

REQUIRED_CONFIG_KEYS = (
    "news_sources",
    "date_time_format",
    "news_update_frequency_in_seconds",
    "locales",
)


def _explicit_config_dir() -> Optional[Path]:
    """
    Optional directory that holds config.json when NEWSFEED_CONFIG_DIR / NEWSFEED_CONFIG is set.
    """
    raw = (
        os.environ.get("NEWSFEED_CONFIG_DIR", "").strip()
        or os.environ.get("NEWSFEED_CONFIG", "").strip()
    )
    return Path(raw).expanduser().resolve() if raw else None


def _repo_newsfeed_config_if_writable() -> Optional[Path]:
    """
    ``newsfeed_config/`` next to this module when developing from a source tree.

    When installed under ``site-packages``, ``…/site-packages/newsfeed_config`` is skipped so we
    do not write next to the wheel (and ``import newsfeed_config`` is not used here, so cwd
    cannot shadow the installed package on ``sys.path``).
    """
    candidate = Path(__file__).resolve().parent / _PACKAGED_CONFIG_PACKAGE
    if not candidate.is_dir():
        return None
    if "site-packages" in candidate.parts:
        return None
    if not os.access(candidate, os.W_OK):
        return None
    return candidate


def _resolve_user_config_path() -> Path:
    base = Path(platformdirs.user_config_dir("newsfeed", appauthor=False))
    return base / _USER_CONFIG_FILE


def _resolve_config_json_path() -> Path:
    explicit = _explicit_config_dir()
    if explicit is not None:
        return explicit / _USER_CONFIG_FILE

    repo_pkg = _repo_newsfeed_config_if_writable()
    if repo_pkg is not None:
        return repo_pkg / _USER_CONFIG_FILE

    return _resolve_user_config_path()


def _validate_config_parent_before_seed(config_path: Path) -> None:
    """
    Before creating config.json, ensure the parent directory is either new, empty, or already
    claimed by this app (marker file and/or existing config.json). Refuse foreign directories
    that happen to use the same path (e.g. ``~/.config/newsfeed`` on Linux).
    """
    parent = config_path.parent
    if parent.exists() and not parent.is_dir():
        raise ValueError(
            f"Cannot create config at {config_path}: {parent} exists and is not a directory."
        )
    if config_path.exists():
        return
    if not parent.exists():
        return
    allowed = {_CONFIG_DIR_MARKER_NAME, _USER_CONFIG_FILE, _UI_STATE_FILE}
    for entry in parent.iterdir():
        if entry.name not in allowed:
            raise ValueError(
                f"Refusing to create {config_path.name} under {parent}: that directory already "
                f"exists and contains {entry.name!r}, which is not from this application. "
                "Remove or relocate those files, or set NEWSFEED_CONFIG_DIR to a dedicated empty "
                "directory."
            )


def _resource_root():
    try:
        return resources.files(_PACKAGED_CONFIG_PACKAGE)
    except ModuleNotFoundError as e:
        raise FileNotFoundError(
            "Packaged newsfeed_config is missing. Reinstall with: uv tool install ."
        ) from e


def _seed_config_if_missing(config_path: Path) -> None:
    """Create config.json by copying packaged config.default.json when missing."""
    if config_path.exists():
        return
    _validate_config_parent_before_seed(config_path)
    root = _resource_root()
    template = root.joinpath(_TEMPLATE_FILE)
    text = template.read_text(encoding="utf-8")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_config_parent_before_seed(config_path)
    marker = config_path.parent / _CONFIG_DIR_MARKER_NAME
    if not marker.exists():
        marker.write_text(
            "Created by the newsfeed CLI to mark this directory.\n", encoding="utf-8"
        )
    config_path.write_text(text, encoding="utf-8")


def _load_json_from_path(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a JSON object: {path}")
    return data


def _load_packaged_defaults() -> Dict[str, Any]:
    root = _resource_root()
    path = root.joinpath(_TEMPLATE_FILE)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Packaged {_TEMPLATE_FILE!r} must contain a JSON object"
        )
    missing_tpl = [k for k in REQUIRED_CONFIG_KEYS if k not in data]
    if missing_tpl:
        raise ValueError(
            f"Packaged {_TEMPLATE_FILE!r} is missing keys: {', '.join(missing_tpl)}. "
            "Your installation may be corrupt; reinstall with: uv tool install --force ."
        )
    return data


def _merge_with_defaults(defaults: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Overlay user config on packaged defaults. Omitted keys use defaults.
    JSON null values are treated as \"use default\" for that key.
    """
    user_overrides = {k: v for k, v in user.items() if v is not None}
    merged: Dict[str, Any] = {**defaults, **user_overrides}
    for key in REQUIRED_CONFIG_KEYS:
        if key not in merged and key in defaults:
            merged[key] = defaults[key]
    return merged


def load_app_config() -> NewsAppConfig:
    """
    Loads ``config.json`` merged on top of packaged ``config.default.json``.
    Any primary key omitted from ``config.json`` uses the default value.

    On first run, ``config.json`` is created by copying the template (you may
    trim keys afterward; missing keys keep resolving from defaults).
    """
    defaults = _load_packaged_defaults()
    config_path = _resolve_config_json_path()
    _seed_config_if_missing(config_path)
    user = _load_json_from_path(config_path)
    data = _merge_with_defaults(defaults, user)

    missing = [k for k in REQUIRED_CONFIG_KEYS if k not in data]
    if missing:
        raise ValueError(
            f"Missing required config keys after merging with defaults: {', '.join(missing)}. "
            f"Config file: {config_path}. Reinstall the tool (uv tool install --force .) "
            "if you upgraded from an older version."
        )

    return NewsAppConfig(
        news_sources=data["news_sources"],
        date_time_format=data["date_time_format"],
        news_update_frequency_in_seconds=data["news_update_frequency_in_seconds"],
        locales=data["locales"],
    )
