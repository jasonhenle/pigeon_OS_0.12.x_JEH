# pigeon.control_api

Companion-app interface (spec: `docs/control_api_v1.md`). Phase 1: identity, claim, status, SSE, manual search.

Off by default. Turn on with `PIGEON_CONTROL_API=1` (or `"control_api": true` in the state file); port `8780`
(`PIGEON_CONTROL_PORT`). `PIGEON_PRODUCT=marquee` switches the capability set. mDNS needs `pip install zeroconf`
(optional; without it the API still runs, just isn't advertised).

Try it:

    curl localhost:8780/api/v1/hello

The claim code is `pigeon.control_api.pairing_code()`; showing it on screen is not wired yet, so for now read it
from a Python shell. Tests: `python3 -m unittest tests.test_control_api`.

`GET /api/v1/search/suggest` returns `200` with an empty `results` array only when the search completed and
found no matches. Search service failures return `503` with a standard `error` object: `tmdb_not_configured`
means the device needs a TMDb API key or read token under `~/.pigeon_0_6/`; `search_unavailable` means the
device could not get a response from TMDb. Clients should show the error message instead of treating these
responses as “no matches.”
