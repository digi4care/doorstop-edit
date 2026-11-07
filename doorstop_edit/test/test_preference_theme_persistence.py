"""Focused persistence coverage using a private INI-backed QSettings store."""

from PySide6.QtCore import QSettings

from doorstop_edit import settings as settings_module
from doorstop_edit.preference_theme import (
    BUILTIN_PROFILES,
    DARK_PROFILE,
    LIGHT_PROFILE,
    ThemeMode,
    ThemePreferences,
    ThemeProfile,
    ThemeProfileStore,
    ThemeTokens,
    resolve_theme,
)


def ini_settings(tmp_path):
    return QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)


def test_custom_profile_persists_between_store_instances(tmp_path):
    profile = ThemeProfile("Ocean", ThemeTokens("#001122", "#112233", "#ffffff", "#00aaff"))

    ThemeProfileStore(ini_settings(tmp_path)).save(profile)

    assert ThemeProfileStore(ini_settings(tmp_path)).load("Ocean") == profile


def test_profile_selection_is_independent_of_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "get_settings", lambda: ini_settings(tmp_path))
    preferences = ThemePreferences()
    preferences.mode = ThemeMode.AUTO.value
    preferences.profile_name = "Ocean"

    reloaded = ThemePreferences()
    assert reloaded.mode == ThemeMode.AUTO.value
    assert reloaded.profile_name == "Ocean"
    resolved = resolve_theme(ThemeMode(reloaded.mode), False, DARK_PROFILE)
    assert resolved.mode is ThemeMode.DAY
    assert resolved.profile is DARK_PROFILE


def test_reset_removes_custom_profiles_and_builtin_defaults_remain(tmp_path):
    store = ThemeProfileStore(ini_settings(tmp_path))
    store.save(ThemeProfile("Ocean", ThemeTokens("#001122", "#112233", "#ffffff", "#00aaff")))

    store.reset()

    assert ThemeProfileStore(ini_settings(tmp_path)).load("Ocean") is None
    assert BUILTIN_PROFILES == {LIGHT_PROFILE.name: LIGHT_PROFILE, DARK_PROFILE.name: DARK_PROFILE}


def test_unknown_profile_name_returns_none(tmp_path):
    assert ThemeProfileStore(ini_settings(tmp_path)).load("Not a profile") is None
