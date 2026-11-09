"""QML-independent preference and theme-token model."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from PySide6.QtCore import QSettings

from doorstop_edit.settings import PersistentSetting, get_settings


@dataclass(frozen=True)
class ThemeTokens:
    background: str
    surface: str
    text: str
    accent: str


@dataclass(frozen=True)
class ThemeProfile:
    name: str
    tokens: ThemeTokens


class ThemeMode(str, Enum):
    AUTO = "Auto"
    DAY = "Day"
    NIGHT = "Night"


class ThemeProfileChoice(str, Enum):
    DAY = "Day"
    DARK_TEAL = "Dark Teal"


class OsColorScheme(str, Enum):
    LIGHT = "Light"
    DARK = "Dark"
    UNKNOWN = "Unknown"


LIGHT_PROFILE = ThemeProfile("Day", ThemeTokens("#ffffff", "#f3f4f6", "#171717", "#2563eb"))
DARK_PROFILE = ThemeProfile("Dark Teal", ThemeTokens("#073b3a", "#0b514f", "#e8f5f4", "#26a69a"))
BUILTIN_PROFILES: Mapping[str, ThemeProfile] = {LIGHT_PROFILE.name: LIGHT_PROFILE, DARK_PROFILE.name: DARK_PROFILE}


@dataclass(frozen=True)
class ResolvedTheme:
    mode: ThemeMode
    profile: ThemeProfile


def resolve_theme(mode: ThemeMode, os_scheme: OsColorScheme | bool, profile: ThemeProfile) -> ResolvedTheme:
    """Resolve appearance independently; Unknown falls back to Night (the existing dark-teal UI)."""
    if mode is ThemeMode.AUTO:
        if os_scheme is True or os_scheme is OsColorScheme.DARK:
            effective_mode = ThemeMode.NIGHT
        elif os_scheme is False or os_scheme is OsColorScheme.LIGHT:
            effective_mode = ThemeMode.DAY
        else:
            effective_mode = ThemeMode.NIGHT
    else:
        effective_mode = mode
    return ResolvedTheme(effective_mode, profile)


class ThemePreferences(PersistentSetting):
    IN_GROUP = "Theme"
    mode = "Night"
    profile_name = "Dark Teal"
    font_size = 12
    density_scale = -1


class SpellcheckerPreferences(PersistentSetting):
    IN_GROUP = "spellchecker"
    enabled = True
    langugage = "en"  # Existing key spelling is kept for compatibility.


class ThemeProfileStore:
    """Per-user QSettings store for custom profiles; built-ins cannot be overwritten."""

    GROUP = "Theme/CustomProfiles"

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()

    def save(self, profile: ThemeProfile) -> None:
        if profile.name in BUILTIN_PROFILES:
            raise ValueError("Built-in profiles are read-only")
        self._settings.beginGroup(self.GROUP)
        self._settings.beginGroup(profile.name)
        for key, value in vars(profile.tokens).items():
            self._settings.setValue(key, value)
        self._settings.endGroup()
        self._settings.endGroup()

    def load(self, name: str) -> ThemeProfile | None:
        self._settings.beginGroup(self.GROUP)
        if name not in self._settings.childGroups():
            self._settings.endGroup()
            return None
        self._settings.beginGroup(name)
        tokens = ThemeTokens(*(str(self._settings.value(k, "")) for k in ("background", "surface", "text", "accent")))
        self._settings.endGroup()
        self._settings.endGroup()
        return ThemeProfile(name, tokens)

    def reset(self) -> None:
        self._settings.remove(self.GROUP)
