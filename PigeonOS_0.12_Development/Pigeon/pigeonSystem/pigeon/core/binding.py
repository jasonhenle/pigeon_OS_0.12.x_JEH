"""Bind extracted ``bootstrap()`` helpers to the app state they depend on."""

from __future__ import annotations

import functools


def bind_deps(fn, /, **deps):
    """Return ``fn`` with its keyword-only dependencies pre-filled.

    Helpers moved out of ``bootstrap()`` take the state they used to close over
    as keyword-only arguments. ``bootstrap()`` calls this once where the old
    nested ``def`` stood, so every existing caller (direct calls, Tk callbacks,
    ``root.after``) keeps working unchanged. Name and docstring are preserved
    for tracebacks and logging.
    """
    bound = functools.partial(fn, **deps)
    functools.update_wrapper(bound, fn)
    return bound


def late(get, name):
    """Callable stand-in for a helper that ``bootstrap()`` binds further down.

    ``get`` is a ``lambda: helper`` written in ``bootstrap()``; it is evaluated
    on every call, exactly like the closure reference it replaces. Calling
    before ``helper`` is bound therefore raises ``NameError`` just as the
    original nested function would have. ``name`` keeps tracebacks and logs
    readable.
    """

    def call(*args, **kwargs):
        return get()(*args, **kwargs)

    call.__name__ = call.__qualname__ = name
    return call


def bind_method_deps(fn, /, **deps):
    """Like :func:`bind_deps`, but returns a plain function so it works as a method.

    ``functools.partial`` is not a descriptor: stored on a class
    (``tk.Widget.pack = ...``) it would be called without ``self``. The wrapper
    returned here is an ordinary function, so attribute lookup binds ``self``
    as it did for the original nested ``def``. Keyword handling matches
    ``partial``: explicit caller keywords win over ``deps``.
    """

    @functools.wraps(fn)
    def method(*args, **kwargs):
        return fn(*args, **{**deps, **kwargs})

    return method
