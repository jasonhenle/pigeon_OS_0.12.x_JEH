"""``pigeon.core.binding.late`` must behave like the closure reference it replaces."""

import unittest

from pigeon.core.binding import bind_deps, late


class LateBindingTests(unittest.TestCase):
    def test_resolves_at_call_time(self) -> None:
        target = {"fn": None}
        proxy = late(lambda: target["fn"], "helper")
        target["fn"] = lambda x, *, y=0: x + y
        self.assertEqual(proxy(1, y=2), 3)
        target["fn"] = lambda x, *, y=0: x * 10
        self.assertEqual(proxy(1), 10)

    def test_unbound_name_raises_name_error_like_a_closure(self) -> None:
        def make():
            proxy = late(lambda: helper, "helper")  # noqa: F821 - bound below
            try:
                proxy()
            except NameError:
                raised = True
            else:
                raised = False

            def helper():
                return "ok"

            return raised, proxy()

        raised, value = make()
        self.assertTrue(raised)
        self.assertEqual(value, "ok")

    def test_keeps_name_for_logs(self) -> None:
        proxy = late(lambda: print, "_render_once")
        self.assertEqual(proxy.__name__, "_render_once")

    def test_recursive_helper_via_late(self) -> None:
        def countdown(n, *, countdown):
            return 0 if n == 0 else 1 + countdown(n - 1)

        bound = None
        bound = bind_deps(countdown, countdown=late(lambda: bound, "countdown"))
        self.assertEqual(bound(5), 5)


if __name__ == "__main__":
    unittest.main()
