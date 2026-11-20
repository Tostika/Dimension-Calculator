"""A do-nothing stand-in for PySide6, used only to smoke-test the UI code on a machine
without Qt: it builds every page and runs the main code paths, which catches typos,
wrong names and logic errors (not how things look)."""
import sys
import types


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Dummy()


class Dummy(metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Dummy()

    def __call__(self, *a, **k):
        return Dummy()

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __index__(self):
        return 0

    def __or__(self, o):
        return Dummy()

    __ror__ = __or__
    __and__ = __or__
    __add__ = __sub__ = __mul__ = __truediv__ = __radd__ = __rmul__ = __or__

    def __lt__(self, o):
        return False

    __gt__ = __le__ = __ge__ = __lt__

    def __str__(self):
        return ""


# methods that the app calls through super(), which skips __getattr__
for _name in ("setText", "resizeEvent", "showEvent", "closeEvent", "paintEvent", "setStyleSheet", "setEnabled"):
    setattr(Dummy, _name, lambda self, *a, **k: Dummy())


def _module(name):
    m = types.ModuleType(name)

    def ga(attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        cls = _Meta(attr, (Dummy,), {})
        setattr(m, attr, cls)
        return cls

    m.__getattr__ = ga
    return m


def install():
    pkg = types.ModuleType("PySide6")
    for sub in ("QtCore", "QtGui", "QtWidgets"):
        mod = _module("PySide6." + sub)
        setattr(pkg, sub, mod)
        sys.modules["PySide6." + sub] = mod
    sys.modules["PySide6"] = pkg
    core = sys.modules["PySide6.QtCore"]
    core.Signal = lambda *a, **k: Dummy()
