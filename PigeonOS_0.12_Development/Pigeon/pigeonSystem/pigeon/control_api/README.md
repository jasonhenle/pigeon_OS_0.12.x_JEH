# pigeon.control_api

Companion-app interface (spec: `docs/control_api_v1.md`). Phase 1: identity, claim, status, SSE, manual search.

Off by default. Turn on with `PIGEON_CONTROL_API=1` (or `"control_api": true` in the state file); port `8780`
(`PIGEON_CONTROL_PORT`). `PIGEON_PRODUCT=marquee` switches the capability set. mDNS needs `pip install zeroconf`
(optional; without it the API still runs, just isn't advertised).

Try it:

    curl localhost:8780/api/v1/hello

The claim code is `pigeon.control_api.pairing_code()`; showing it on screen is not wired yet, so for now read it
from a Python shell. Tests: `python3 -m unittest tests.test_control_api`.
