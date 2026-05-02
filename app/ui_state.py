"""
TUI preferences on disk. Lives under ``app/`` so imports never collide with the PyPI
``config`` package or another tool that installs a top-level ``config`` module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import platformdirs

from newsfeed_app_config import (
    _repo_newsfeed_config_if_writable,
    _resolve_config_json_path,
)

_UI_STATE_FILE = "ui_state.json"

# Maximum articles per source in per-source view (UI input and disk state use this cap).
MAX_PER_SOURCE_ARTICLES = 50

_VIEW_MODES_FROZEN = frozenset(
    {"chronological", "per_source", "by_matching_words"}
)
_VOIKKO_SHARED_K_VALID = frozenset({1, 2, 3, 4})


def _resolve_ui_state_path() -> Path:
    """
    Always ``{user_config_dir}/newsfeed/ui_state.json`` (e.g. ``~/.config/newsfeed`` on Linux).
    """
    return Path(platformdirs.user_config_dir("newsfeed", appauthor=False)) / _UI_STATE_FILE


def ui_state_file_path() -> Path:
    """Absolute path to ``ui_state.json`` (for troubleshooting)."""
    return _resolve_ui_state_path().resolve()


def _legacy_ui_state_paths() -> list[Path]:
    canonical = _resolve_ui_state_path()
    seen: set[Path] = {canonical.resolve()}
    out: list[Path] = []
    sidecar = _resolve_config_json_path().parent / _UI_STATE_FILE
    if sidecar.resolve() not in seen:
        out.append(sidecar)
        seen.add(sidecar.resolve())
    repo_rw = _repo_newsfeed_config_if_writable()
    if repo_rw is not None:
        legacy = repo_rw / _UI_STATE_FILE
        if legacy.resolve() not in seen:
            out.append(legacy)
    return out


def _parse_ui_state_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    vm = data.get("view_mode")
    if isinstance(vm, str):
        vm = vm.strip()
        if vm in _VIEW_MODES_FROZEN:
            out["view_mode"] = vm
    # Cap must match ``_MAX_SPLIT_COLUMNS`` in ``app/main.py`` (currently 4).
    cc = data.get("column_count")
    if isinstance(cc, int) and cc >= 1:
        out["column_count"] = min(cc, 4)
    elif isinstance(cc, float) and cc.is_integer():
        cci = int(cc)
        if cci >= 1:
            out["column_count"] = min(cci, 4)
    sc = data.get("split_columns")
    if isinstance(sc, bool):
        out["split_columns"] = sc
    elif sc in (0, 1):
        out["split_columns"] = bool(sc)
    vk = data.get("voikko_min_shared_k")
    if isinstance(vk, bool):
        pass
    elif isinstance(vk, int) and vk in _VOIKKO_SHARED_K_VALID:
        out["voikko_min_shared_k"] = vk
    elif isinstance(vk, float) and vk.is_integer():
        vi = int(vk)
        if vi in _VOIKKO_SHARED_K_VALID:
            out["voikko_min_shared_k"] = vi
    ps = data.get("per_source_article_limit")
    if isinstance(ps, int) and ps >= 1:
        out["per_source_article_limit"] = min(ps, MAX_PER_SOURCE_ARTICLES)
    elif isinstance(ps, float) and ps.is_integer():
        pi = int(ps)
        if pi >= 1:
            out["per_source_article_limit"] = min(pi, MAX_PER_SOURCE_ARTICLES)
    return out


def _parse_ui_state_from_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return _parse_ui_state_dict(data)


def _prune_legacy_ui_state_sidecars() -> None:
    canonical = _resolve_ui_state_path()
    if not canonical.exists():
        return
    for leg in _legacy_ui_state_paths():
        if leg.resolve() == canonical.resolve():
            continue
        try:
            if leg.exists():
                leg.unlink()
        except OSError:
            pass


def load_ui_state() -> Dict[str, Any]:
    """
    Last-saved TUI preferences. Missing file or invalid JSON yields ``{}``.
    """
    canonical = _resolve_ui_state_path()
    parsed = _parse_ui_state_from_file(canonical)
    if parsed:
        return parsed

    for legacy in _legacy_ui_state_paths():
        migrated = _parse_ui_state_from_file(legacy)
        if migrated:
            save_ui_state(migrated)
            return migrated
    return {}


def save_ui_state(state: Dict[str, Any]) -> None:
    path = _resolve_ui_state_path()
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(
            f"newsfeed: could not create directory for UI state {path.parent}: {exc}",
            file=sys.stderr,
        )
        return
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
        _prune_legacy_ui_state_sidecars()
        return
    except OSError as exc_atomic:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        try:
            path.write_text(payload, encoding="utf-8")
            _prune_legacy_ui_state_sidecars()
        except OSError as exc_direct:
            print(
                f"newsfeed: could not write UI state file {path}: {exc_direct} "
                f"(after atomic write failed: {exc_atomic})",
                file=sys.stderr,
            )
