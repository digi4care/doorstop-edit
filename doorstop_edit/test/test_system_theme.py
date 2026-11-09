from typing import cast

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QStyleHints

from doorstop_edit.preference_theme import DARK_PROFILE, OsColorScheme, ThemeMode, resolve_theme
from doorstop_edit.system_theme import SystemThemeMonitor, map_qt_color_scheme


class FakeStyleHints(QObject):
    colorSchemeChanged = Signal(object)

    def __init__(self, color_scheme: Qt.ColorScheme) -> None:
        super().__init__()
        self.colorScheme = color_scheme

    def set_color_scheme(self, color_scheme: Qt.ColorScheme) -> None:
        self.colorScheme = color_scheme
        self.colorSchemeChanged.emit(color_scheme)


def get_dark_scheme() -> Qt.ColorScheme:
    return Qt.ColorScheme.Dark


def test_maps_initial_os_scheme_and_follows_changes(qapp: object) -> None:
    hints = FakeStyleHints(Qt.ColorScheme.Light)
    monitor = SystemThemeMonitor(cast(QStyleHints, hints))
    changes: list[str] = []
    monitor.colorSchemeChanged.connect(lambda: changes.append(cast(str, monitor.colorScheme)))

    assert str(monitor.colorScheme) == "Light"
    hints.set_color_scheme(get_dark_scheme())
    assert changes == ["Dark"]
    assert monitor.colorScheme == "Dark"


def test_unknown_scheme_uses_existing_night_fallback() -> None:
    assert map_qt_color_scheme(Qt.ColorScheme.Unknown) is OsColorScheme.UNKNOWN
    resolved = resolve_theme(ThemeMode.AUTO, OsColorScheme.UNKNOWN, DARK_PROFILE)
    assert resolved.mode is ThemeMode.NIGHT
