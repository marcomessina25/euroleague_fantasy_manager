"""EuroLeague (and EuroCup) Fantasy Challenge local-first decision engine."""

from __future__ import annotations

import importlib.metadata

__all__ = ["__version__"]

try:
    __version__ = importlib.metadata.version("euroleague-fantasy-manager")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.6.5"
