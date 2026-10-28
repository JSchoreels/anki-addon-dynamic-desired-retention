from __future__ import annotations

import json
import logging
from copy import deepcopy
from types import SimpleNamespace

from anki.collection import Collection as AnkiCollection

import dynamic_desired_retention.addon as addon_module
from dynamic_desired_retention.addon import DynamicDesiredRetentionAddon
from dynamic_desired_retention.synced_rules import BACKUP_NAME, COLLECTION_CONFIG_KEY


class Manager:
    def __init__(self, config: dict, root) -> None:
        self.config = deepcopy(config)
        self.writes: list[dict] = []
        self.root = root

    def addonFromModule(self, _module: str) -> str:
        return "test"

    def addonsFolder(self, _addon: str) -> str:
        return str(self.root)

    def getConfig(self, _module: str) -> dict:
        return deepcopy(self.config)

    def writeConfig(self, _module: str, config: dict) -> None:
        self.config = deepcopy(config)
        self.writes.append(deepcopy(config))


class Collection:
    def __init__(self, value: object = None) -> None:
        self.value = deepcopy(value)
        self.writes: list[object] = []

    def get_config(self, key: str) -> object:
        assert key == COLLECTION_CONFIG_KEY
        return deepcopy(self.value)

    def set_config(self, key: str, value: object) -> None:
        assert key == COLLECTION_CONFIG_KEY
        self.value = deepcopy(value)
        self.writes.append(deepcopy(value))


def addon_with_config(monkeypatch, tmp_path, config: dict, synced: object = None):
    manager = Manager(config, tmp_path)
    collection = Collection(synced)
    window = SimpleNamespace(addonManager=manager, col=collection)
    monkeypatch.setattr(addon_module, "mw", window)
    monkeypatch.setattr(
        addon_module,
        "_notify_rwkv_dynamic_desired_retention_changed",
        lambda _logger: None,
    )
    addon = DynamicDesiredRetentionAddon(
        module="test", logger=logging.getLogger("test")
    )
    return addon, window, manager, collection


def test_profile_open_does_not_automatically_migrate_local_rules(
    monkeypatch, tmp_path
) -> None:
    rule = {"query": "tag:priority", "desired_retention": 0.9}
    addon, _window, manager, collection = addon_with_config(
        monkeypatch, tmp_path, {"rules": [rule], "private_preference": "local"}
    )
    addon._on_profile_opened()
    assert collection.writes == []
    addon._on_config_updated()
    assert collection.value == {
        "version": 1,
        "rules": [rule],
        "field_rules": [],
        "grade_rules": [],
    }
    assert manager.config["private_preference"] == "local"
    addon._on_profile_opened()
    assert len(collection.writes) == 1


def test_existing_synced_rules_win_and_preserve_other_local_config(
    monkeypatch, tmp_path
) -> None:
    synced = {
        "version": 1,
        "rules": [{"query": "deck:Remote", "desired_retention": 0.8}],
        "field_rules": [],
        "grade_rules": [{"grade": "easy", "mode": "absolute", "value": 0.95}],
    }
    addon, _window, manager, collection = addon_with_config(
        monkeypatch, tmp_path, {"rules": [], "private_preference": 7}, synced
    )
    addon._on_profile_opened()
    assert manager.config == {
        **{k: v for k, v in synced.items() if k != "version"},
        "private_preference": 7,
    }
    assert addon._rules[0].query == "deck:Remote"
    assert addon._grade_rules[0].grade == "easy"
    assert collection.writes == []


def test_edit_and_sync_update_both_rule_sources(monkeypatch, tmp_path) -> None:
    addon, _window, manager, collection = addon_with_config(
        monkeypatch, tmp_path, {"rules": []}
    )
    addon._on_profile_opened()
    assert collection.writes == []
    manager.config["rules"] = [{"query": "deck:Local", "desired_retention": 0.9}]
    addon._on_config_updated()
    assert collection.value["rules"] == manager.config["rules"]
    collection.value["rules"] = [{"query": "deck:Synced", "desired_retention": 0.75}]
    addon._on_sync_finished()
    assert manager.config["rules"] == collection.value["rules"]
    assert addon._rules[0].query == "deck:Synced"
    assert len(collection.writes) == 1
    backup_path = tmp_path / "user_files" / BACKUP_NAME
    assert (
        json.loads(backup_path.read_text(encoding="utf8"))["rules"][0]["query"]
        == "deck:Local"
    )
    collection.value["rules"] = [{"query": "deck:Later", "desired_retention": 0.7}]
    addon._on_sync_finished()
    assert (
        json.loads(backup_path.read_text(encoding="utf8"))["rules"][0]["query"]
        == "deck:Local"
    )


def test_unknown_synced_version_is_not_overwritten(monkeypatch, tmp_path) -> None:
    future = {"version": 2, "rules": ["future format"]}
    addon, _window, manager, collection = addon_with_config(
        monkeypatch,
        tmp_path,
        {"rules": [{"query": "deck:Local", "desired_retention": 0.9}]},
        future,
    )
    addon._on_profile_opened()
    addon._on_config_updated()
    assert collection.value == future
    assert collection.writes == []
    assert manager.config["rules"][0]["query"] == "deck:Local"


def test_edit_without_profile_is_applied_when_one_opens(monkeypatch, tmp_path) -> None:
    old = {"version": 1, "rules": [], "field_rules": [], "grade_rules": []}
    addon, window, manager, collection = addon_with_config(
        monkeypatch, tmp_path, {"rules": []}, old
    )
    window.col = None
    manager.config["rules"] = [{"query": "tag:new", "desired_retention": 0.85}]
    addon._on_config_updated()
    window.col = collection
    addon._on_profile_opened()
    assert collection.value["rules"] == manager.config["rules"]
    assert addon._rules[0].query == "tag:new"


def test_rules_persist_through_the_anki_collection_config_api(
    monkeypatch, tmp_path
) -> None:
    local = {"rules": [{"query": "tag:priority", "desired_retention": 0.9}]}
    addon, window, _manager, _fake_collection = addon_with_config(
        monkeypatch, tmp_path, local
    )
    path = str(tmp_path / "synthetic.anki2")
    collection = AnkiCollection(path)
    try:
        window.col = collection
        addon._on_profile_opened()
        assert collection.get_config(COLLECTION_CONFIG_KEY) is None
        addon._on_config_updated()
        assert collection.get_config(COLLECTION_CONFIG_KEY)["rules"] == local["rules"]
    finally:
        collection.close()

    reopened = AnkiCollection(path)
    try:
        assert reopened.get_config(COLLECTION_CONFIG_KEY)["rules"] == local["rules"]
    finally:
        reopened.close()


def test_backup_failure_keeps_local_config_and_uses_synced_rules(
    monkeypatch, tmp_path
) -> None:
    local = {"rules": [{"query": "deck:Local", "desired_retention": 0.9}]}
    remote = {
        "version": 1,
        "rules": [{"query": "deck:Remote", "desired_retention": 0.8}],
    }
    addon, _window, manager, _collection = addon_with_config(
        monkeypatch, tmp_path, local, remote
    )
    monkeypatch.setattr(addon_module, "backup_local_rules", lambda *_args: False)
    addon._on_profile_opened()
    assert manager.config == local
    assert addon._rules[0].query == "deck:Remote"
