from __future__ import annotations

import json
from copy import deepcopy
from logging import Logger
from pathlib import Path
from typing import Any

# Only scheduling rules are shared. Other add-on configuration stays local.
COLLECTION_CONFIG_KEY = "dynamicDesiredRetentionRules"
SCHEMA_VERSION = 1
RULE_KEYS = ("rules", "field_rules", "grade_rules")
MISSING = object()
UNAVAILABLE = object()
BACKUP_NAME = "dynamic_dr_rules_before_sync_v1.json"


def rules_for_sync(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    return {
        "version": SCHEMA_VERSION,
        **{key: deepcopy(config.get(key, [])) for key in RULE_KEYS},
    }


def read_rules(collection: Any, logger: Logger) -> dict[str, Any] | object:
    get_config = getattr(collection, "get_config", None)
    if not callable(get_config):
        return UNAVAILABLE
    try:
        value = get_config(COLLECTION_CONFIG_KEY)
    except Exception:
        logger.exception("failed to read synced Dynamic DR rules")
        return UNAVAILABLE
    if value is None:
        return MISSING
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value.get("version") != SCHEMA_VERSION
    ):
        logger.warning(
            "unsupported synced Dynamic DR rule format; leaving it unchanged"
        )
        return UNAVAILABLE
    return value


def write_rules(collection: Any, config: dict[str, Any], logger: Logger) -> bool:
    existing = read_rules(collection, logger)
    if existing is UNAVAILABLE:
        return False
    updated = rules_for_sync(config)
    if existing == updated:
        return True
    set_config = getattr(collection, "set_config", None)
    if not callable(set_config):
        return False
    try:
        set_config(COLLECTION_CONFIG_KEY, updated)
    except Exception:
        logger.exception("failed to save synced Dynamic DR rules")
        return False
    return True


def local_config_with_rules(
    local_config: dict[str, Any] | None, synced: dict[str, Any]
) -> dict[str, Any]:
    local = deepcopy(local_config) if isinstance(local_config, dict) else {}
    for key in RULE_KEYS:
        local[key] = deepcopy(synced.get(key, []))
    return local


def backup_local_rules(
    manager: Any, module: str, config: dict[str, Any], logger: Logger
) -> bool:
    """Preserve the pre-sync rules before mirroring different synced rules."""
    if not any(config.get(key) for key in RULE_KEYS):
        return True
    try:
        addon_id = manager.addonFromModule(module)
        path = Path(manager.addonsFolder(addon_id)) / "user_files" / BACKUP_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf8") as output:
                json.dump(rules_for_sync(config), output, ensure_ascii=False, indent=2)
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf8"))
            if (
                not isinstance(existing, dict)
                or existing.get("version") != SCHEMA_VERSION
                or not all(key in existing for key in RULE_KEYS)
            ):
                raise ValueError("existing Dynamic DR rules backup is invalid")
    except Exception:
        logger.exception("could not preserve local Dynamic DR rules before sync")
        return False
    return True
