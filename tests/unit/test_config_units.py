"""Unit tests for config path resolution, the loader, and the line locator."""

from __future__ import annotations

from pathlib import Path

import pytest

from iknowwhatyoudid.config import locate
from iknowwhatyoudid.config.location import (
    credentials_path_for,
    default_config_path,
    resolve_config_path,
)
from iknowwhatyoudid.config.loader import load, valid_name
from iknowwhatyoudid.kinds.spec import SettingSpec, SettingType

SAMPLE = """version = 1

[[source]]
name = "one"
kind = "fixture"
recorded = ["a.jsonl"]

[[source]]
name = "two"
kind = "git.local"
paths = ["~/dev"]
identities = ["me@example.com"]
"""


# --- location -----------------------------------------------------------------------


def test_windows_uses_roaming_appdata() -> None:
    """Configuration is hand-authored and roams; the store does not."""
    path = default_config_path({"APPDATA": r"C:\Users\x\AppData\Roaming"}, "win32")
    assert path.as_posix().endswith("Roaming/iknowwhatyoudid/config.toml")


def test_linux_falls_back_when_xdg_is_unset() -> None:
    path = default_config_path({}, "linux")
    assert path.as_posix().endswith(".config/iknowwhatyoudid/config.toml")


def test_linux_honours_xdg_config_home() -> None:
    path = default_config_path({"XDG_CONFIG_HOME": "/tmp/cfg"}, "linux")
    assert path.as_posix() == "/tmp/cfg/iknowwhatyoudid/config.toml"


def test_macos_uses_application_support() -> None:
    assert "Application Support" in default_config_path({}, "darwin").as_posix()


def test_an_override_wins_over_the_default() -> None:
    assert resolve_config_path("elsewhere.toml") == Path("elsewhere.toml")


def test_credentials_sit_beside_the_configuration() -> None:
    """So --config selects a whole configuration, not a half of one."""
    assert credentials_path_for(Path("/a/b/config.toml")) == Path(
        "/a/b/credentials.toml"
    )


# --- loader -------------------------------------------------------------------------


def test_dotted_keys_survive_as_the_user_wrote_them(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[[source]]\nname = "m"\nkind = "mail.outlook"\n'
        'addresses = ["me@x.com"]\nfolders.include = ["Inbox"]\n',
        encoding="utf-8",
    )
    configuration, _ = load(config)
    assert configuration.sources[0].settings["folders.include"] == ["Inbox"]


def test_reserved_keys_are_not_treated_as_settings(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(SAMPLE, encoding="utf-8")
    configuration, _ = load(config)

    for reserved in ("name", "kind", "enabled", "since", "credential"):
        assert reserved not in configuration.sources[0].settings


def test_sources_keep_file_order(tmp_path: Path) -> None:
    """Output must match what the user sees in their editor."""
    config = tmp_path / "config.toml"
    config.write_text(SAMPLE, encoding="utf-8")
    configuration, _ = load(config)
    assert [s.name for s in configuration.sources] == ["one", "two"]


@pytest.mark.parametrize(
    "name,ok",
    [
        ("work-mail", True),
        ("a.b_c-1", True),
        ("1abc", True),
        ("-nope", False),
        ("has space", False),
        ("", False),
    ],
)
def test_name_rules(name: str, ok: bool) -> None:
    assert valid_name(name) is ok


# --- locate: best-effort, never a wrong line ----------------------------------------


def test_a_key_written_once_is_located() -> None:
    assert locate.find_key_line(SAMPLE, 0, "name") == 4
    assert locate.find_key_line(SAMPLE, 1, "name") == 9


def test_an_absent_key_returns_none_rather_than_guessing() -> None:
    assert locate.find_key_line(SAMPLE, 0, "nonexistent") is None


def test_an_out_of_range_source_returns_none() -> None:
    assert locate.find_key_line(SAMPLE, 9, "name") is None
    assert locate.find_source_line(SAMPLE, 9) is None


def test_a_top_level_key_is_located() -> None:
    assert locate.find_top_level_key_line(SAMPLE, "version") == 1


def test_a_repeated_key_returns_none() -> None:
    """Ambiguity yields no line, never the wrong one."""
    text = '[[source]]\nname = "a"\nname = "b"\n'
    assert locate.find_key_line(text, 0, "name") is None


# --- SettingSpec type checking ------------------------------------------------------


@pytest.mark.parametrize(
    "setting_type,value,ok",
    [
        (SettingType.STRING, "x", True),
        (SettingType.STRING, 1, False),
        (SettingType.INTEGER, 3, True),
        (SettingType.INTEGER, True, False),  # bool is an int subclass; must not pass
        (SettingType.BOOL, True, True),
        (SettingType.STRING_LIST, ["a", "b"], True),
        (SettingType.STRING_LIST, ["a", 2], False),
        (SettingType.STRING_LIST, "a", False),
        (SettingType.PATH_LIST, ["~/dev"], True),
    ],
)
def test_setting_accepts(setting_type: SettingType, value: object, ok: bool) -> None:
    assert SettingSpec("k", setting_type).accepts(value) is ok


def test_an_empty_override_is_refused_not_resolved() -> None:
    """An empty --config/--store is an unset shell variable, not a request for `.`."""
    from iknowwhatyoudid.errors import UsageError
    from iknowwhatyoudid.store.location import resolve_store_path

    for resolve in (resolve_config_path, resolve_store_path):
        with pytest.raises(UsageError):
            resolve("")
        with pytest.raises(UsageError):
            resolve("   ")
