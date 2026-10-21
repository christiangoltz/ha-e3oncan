"""Load the integration's pure-Python modules without Home Assistant."""

import importlib.util
import pathlib
import sys
import types

PKG_DIR = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "e3oncan"

# Register the package without executing __init__.py (which imports Home Assistant).
pkg = types.ModuleType("e3oncan")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["e3oncan"] = pkg
