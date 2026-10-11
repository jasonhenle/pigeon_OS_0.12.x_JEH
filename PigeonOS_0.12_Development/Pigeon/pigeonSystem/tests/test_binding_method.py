"""``bind_method_deps`` must work where ``bind_deps`` cannot: stored on a class."""

import functools
import unittest

from pigeon.core.binding import bind_deps, bind_method_deps


def _patched(self, *args, _orig, _after, **kwargs):
    """Doc kept."""
    r = _orig(self, *args, **kwargs)
    _after()
    return r


class BindMethodDepsTests(unittest.TestCase):
    def _cls(self):
        class W:
            def pack(self, *args, **kwargs):
                return (self, args, kwargs)

        return W

    def test_receives_self_when_stored_on_a_class(self) -> None:
        W = self._cls()
        seen = []
        W.pack = bind_method_deps(_patched, _orig=W.pack, _after=lambda: seen.append(1))
        w = W()
        self.assertEqual(w.pack(1, fill="both"), (w, (1,), {"fill": "both"}))
        self.assertEqual(seen, [1])

    def test_partial_would_not(self) -> None:
        if hasattr(functools.partial, "__get__"):
            # Python 3.14 made partial a method descriptor, so on a class it
            # binds self by itself and the premise of this test no longer holds.
            # bind_method_deps stays correct there (see the other tests).
            self.skipTest("functools.partial binds self on Python >= 3.14")
        W = self._cls()
        W.pack = bind_deps(_patched, _orig=W.pack, _after=lambda: None)
        with self.assertRaises(TypeError):
            W().pack()

    def test_kwargs_keep_their_keys_and_metadata(self) -> None:
        W = self._cls()
        m = bind_method_deps(_patched, _orig=W.pack, _after=lambda: None)
        self.assertEqual(m.__name__, "_patched")
        self.assertEqual(m.__doc__, "Doc kept.")
        _s, _a, kw = m(W(), side="top")
        self.assertEqual(kw, {"side": "top"})


if __name__ == "__main__":
    unittest.main()
