from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from doorstop_edit.preference_theme import (
    BUILTIN_PROFILES,
    DARK_PROFILE,
    LIGHT_PROFILE,
    OsColorScheme,
    SpellcheckerPreferences,
    ThemeMode,
    ThemePreferences,
    ThemeProfile,
    ThemeProfileChoice,
    ThemeProfileStore,
    ThemeTokens,
    resolve_theme,
)


def isolate_real_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from doorstop_edit import settings as settings_module

    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: QSettings(
            QSettings.Format.NativeFormat,
            QSettings.Scope.UserScope,
            "doorstop-edit",
            "doorstop-edit",
        ),
    )


def test_defaults_and_auto_resolution() -> None:
    assert ThemePreferences.font_size == 12
    assert ThemePreferences.density_scale == -1
    assert ThemePreferences.mode == ThemeMode.NIGHT.value
    assert ThemePreferences.profile_name == ThemeProfileChoice.DARK_TEAL.value
    assert SpellcheckerPreferences.enabled is True
    assert SpellcheckerPreferences.langugage == "en"
    assert resolve_theme(ThemeMode.AUTO, False, DARK_PROFILE).mode is ThemeMode.DAY
    assert resolve_theme(ThemeMode.AUTO, True, LIGHT_PROFILE).mode is ThemeMode.NIGHT
    assert resolve_theme(ThemeMode.AUTO, OsColorScheme.UNKNOWN, LIGHT_PROFILE).mode is ThemeMode.NIGHT
    assert resolve_theme(ThemeMode.NIGHT, False, LIGHT_PROFILE).mode is ThemeMode.NIGHT
    assert resolve_theme(ThemeMode.AUTO, False, DARK_PROFILE).profile is DARK_PROFILE


def test_profile_persistence_reload_and_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_real_settings(tmp_path, monkeypatch)
    profile = ThemeProfile("Ocean", ThemeTokens("#001122", "#112233", "#ffffff", "#00aaff"))
    ThemeProfileStore().save(profile)
    assert ThemeProfileStore().load("Ocean") == profile
    ThemeProfileStore().reset()
    assert ThemeProfileStore().load("Ocean") is None
    assert ThemeProfileStore().load(DARK_PROFILE.name) is None
    assert BUILTIN_PROFILES[DARK_PROFILE.name] == DARK_PROFILE


def test_selection_and_legacy_settings_persist_independently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_real_settings(tmp_path, monkeypatch)
    prefs = ThemePreferences()
    prefs.mode = ThemeMode.DAY.value
    prefs.profile_name = "Ocean"
    prefs.font_size = 15
    spell = SpellcheckerPreferences()
    spell.langugage = "fr"
    settings = QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, "doorstop-edit", "doorstop-edit")
    assert settings.value("Theme/mode", type=str) == "Day"
    assert settings.value("Theme/profile_name", type=str) == "Ocean"
    assert settings.value("Theme/font_size", type=int) == 15
    assert settings.value("spellchecker/langugage", type=str) == "fr"
    reloaded = ThemePreferences()
    assert reloaded.mode == "Day"
    assert reloaded.profile_name == "Ocean"
    assert resolve_theme(ThemeMode(reloaded.mode), False, DARK_PROFILE).profile == DARK_PROFILE
    assert SpellcheckerPreferences().langugage == "fr"
