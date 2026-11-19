from importlib.metadata import PackageNotFoundError, version

__project__ = "doorstop-edit"

try:
    __version__ = version(__project__)
except PackageNotFoundError:
    __version__ = "(local)"
