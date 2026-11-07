"""Observable adapter for the operating-system color-scheme preference."""

from PySide6.QtCore import Property, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication

from doorstop_edit.preference_theme import OsColorScheme


def map_qt_color_scheme(value: Qt.ColorScheme) -> OsColorScheme:
    if value == Qt.ColorScheme.Light:
        return OsColorScheme.LIGHT
    if value == Qt.ColorScheme.Dark:
        return OsColorScheme.DARK
    return OsColorScheme.UNKNOWN


class SystemThemeMonitor(QObject):
    """Expose QStyleHints color-scheme changes as a small QML-friendly property.

    Pass a style-hints object for tests; production callers may omit it to use
    the active QGuiApplication. The monitor observes the platform preference
    only; theme selection and palette resolution remain with the caller.
    """

    colorSchemeChanged = Signal()

    def __init__(self, style_hints: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        if style_hints is None:
            application = QGuiApplication.instance()
            if application is None:
                raise RuntimeError("SystemThemeMonitor requires a QGuiApplication")
            style_hints = application.styleHints()
        self._style_hints = style_hints
        self._style_hints.colorSchemeChanged.connect(self._on_color_scheme_changed)

    @Property(str, notify=colorSchemeChanged)
    def colorScheme(self) -> str:
        return map_qt_color_scheme(self._style_hints.colorScheme).value

    def _on_color_scheme_changed(self, *_args: object) -> None:
        self.colorSchemeChanged.emit()
