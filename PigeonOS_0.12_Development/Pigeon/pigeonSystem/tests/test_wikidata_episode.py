"""Wikidata episode → series fallback (pigeon/wikidata_episode.py), offline."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import wikidata_episode as wd  # noqa: E402


def _claim(value) -> dict:
    v = {"id": value} if str(value).startswith("Q") else value
    return {"mainsnak": {"datavalue": {"value": v}}}


def _ent(p31=(), p179=(), label="", tmdb=None) -> dict:
    claims: dict = {"P31": [_claim(x) for x in p31], "P179": [_claim(x) for x in p179]}
    if tmdb is not None:
        claims["P4983"] = [_claim(tmdb)]
    return {"labels": {"en": {"value": label}} if label else {}, "claims": claims}


_TV_EPISODE = "Q21191270"
_OFFICE = "Q23831"

# Trimmed from real ``wbsearchentities`` / ``wbgetentities`` responses.
_SEARCH = {
    "Weight Loss": [
        {"id": "Q1", "label": "weight loss", "description": "reduction of the total body mass"},
        {"id": "Q2", "label": "Weight Loss", "description": "two-part episode of The Office"},
        {"id": "Q3", "label": "Weight Loss (part 1)", "description": "episode of The Office (S5 E1)"},
        {"id": "Q4", "label": "Weight Loss (part 2)", "description": "episode of The Office (S5 E2)"},
    ],
    "Business Ethics": [
        {"id": "Q10", "label": "Business Ethics", "description": "journal"},
        {
            "id": "Q11",
            "label": "Business Ethics",
            "description": "third episode of the fifth season of the US television series The Office",
        },
        {"id": "Q12", "label": "Business Ethics", "description": "2019 Canadian film"},
    ],
    "Baby Shower": [
        {"id": "Q40", "label": "Baby Shower", "description": "episode of The Office (S5 E4)"},
        {"id": "Q41", "label": "Baby Shower", "description": "episode of ER (S7 E3)"},
        {"id": "Q42", "label": "Baby Shower", "description": "episode of Superstore (S2 E4)"},
    ],
    "Pilot": [
        {"id": "Q20", "label": "Pilot", "description": "episode of Welcome to Night Vale published on June 15 2012 (E1)"},
        {"id": "Q21", "label": "Pilot", "description": "episode of Manifest (S1 E1)"},
    ],
}
_ENTITIES = {
    "Q1": _ent(p31=["Q8"]),
    "Q2": _ent(p31=["Q21664088"], p179=[_OFFICE]),
    "Q3": _ent(p31=[_TV_EPISODE], p179=[_OFFICE]),
    "Q4": _ent(p31=[_TV_EPISODE], p179=[_OFFICE]),
    "Q10": _ent(p31=["Q5633421"]),
    "Q11": _ent(p31=[_TV_EPISODE], p179=[_OFFICE]),
    "Q12": _ent(p31=["Q11424"]),
    "Q20": _ent(p31=["Q61855877"], p179=["Q30"]),
    "Q21": _ent(p31=[_TV_EPISODE], p179=["Q31"]),
    "Q40": _ent(p31=[_TV_EPISODE], p179=[_OFFICE]),
    "Q41": _ent(p31=[_TV_EPISODE], p179=["Q50"]),
    "Q42": _ent(p31=[_TV_EPISODE], p179=["Q51"]),
    _OFFICE: _ent(label="The Office", tmdb="2316"),
    "Q50": _ent(label="ER", tmdb="4588"),
    "Q51": _ent(label="Superstore", tmdb="62649"),
    "Q30": _ent(label="Welcome to Night Vale"),
    "Q31": _ent(label="Manifest", tmdb="79696"),
}


def _fake_api(params: dict[str, str], **_kw) -> dict:
    if params["action"] == "wbsearchentities":
        # Wikidata prefix search returns nothing for ``Weight Loss Part 2``.
        return {"search": _SEARCH.get(params["search"], [])}
    ids = params["ids"].split("|")
    return {"entities": {i: _ENTITIES[i] for i in ids if i in _ENTITIES}}


class PartSuffixTests(unittest.TestCase):
    def test_split_part_suffix(self) -> None:
        self.assertEqual(wd._split_part_suffix("Weight Loss Part 2"), ("Weight Loss", "2"))
        self.assertEqual(wd._split_part_suffix("Weight Loss (part 2)"), ("Weight Loss", "2"))
        self.assertEqual(wd._split_part_suffix("Weight Loss - Pt. Two"), ("Weight Loss", "2"))
        self.assertEqual(wd._split_part_suffix("Goodbye, Part II"), ("Goodbye", "2"))
        self.assertIsNone(wd._split_part_suffix("Departure"))
        self.assertIsNone(wd._split_part_suffix("Part 2"))


class SeriesLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        wd.clear_wikidata_episode_cache()
        patcher = mock.patch.object(wd, "_http_json", side_effect=_fake_api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_part_title_resolves_via_base_search(self) -> None:
        self.assertEqual(
            wd.series_from_wikidata_episode_title("Weight Loss Part 2"),
            {"name": "The Office", "tmdb_tv_id": 2316},
        )

    def test_two_part_umbrella_and_unknown_part(self) -> None:
        self.assertEqual(wd.series_name_from_wikidata_episode_title("Weight Loss"), "The Office")
        self.assertIsNone(wd.series_name_from_wikidata_episode_title("Weight Loss Part Three"))

    def test_free_text_description_uses_series_claim(self) -> None:
        # Same-named film and journal are not episodes and do not add ambiguity.
        self.assertEqual(
            wd.series_from_wikidata_episode_title("Business Ethics"),
            {"name": "The Office", "tmdb_tv_id": 2316},
        )

    def test_episodes_of_two_series_stay_ambiguous(self) -> None:
        self.assertIsNone(wd.series_from_wikidata_episode_title("Pilot"))

    def test_ambiguous_title_lists_every_series(self) -> None:
        self.assertIsNone(wd.series_from_wikidata_episode_title("Baby Shower"))
        self.assertEqual(
            wd.series_candidates_from_wikidata_episode_title("Baby Shower"),
            [
                {"name": "The Office", "tmdb_tv_id": 2316},
                {"name": "ER", "tmdb_tv_id": 4588},
                {"name": "Superstore", "tmdb_tv_id": 62649},
            ],
        )


class PickSeriesTests(unittest.TestCase):
    """tmdb_poster picks among ambiguous Wikidata candidates."""

    _CANDS = [
        {"name": "The Office", "tmdb_tv_id": 2316},
        {"name": "ER", "tmdb_tv_id": 4588},
        {"name": "Superstore", "tmdb_tv_id": 62649},
    ]

    def setUp(self) -> None:
        from pigeon import tmdb_poster as tp

        self.tp = tp
        tp.clear_recent_episode_series()
        self.addCleanup(tp.clear_recent_episode_series)
        # Peacock (386) carries The Office and Superstore; ER is on Hulu (15).
        self.providers_by_id: dict[int, frozenset[int] | None] = {
            2316: frozenset({386}),
            62649: frozenset({386}),
            4588: frozenset({15}),
        }
        patcher = mock.patch.object(
            tp, "_tmdb_watch_provider_ids", side_effect=lambda _k, i: self.providers_by_id.get(i)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def pick(self, service: str = "Peacock"):
        return self.tp._pick_wikidata_episode_series(
            list(self._CANDS), service=service, providers=frozenset({386})
        )

    def test_ambiguous_without_history_stays_unresolved(self) -> None:
        self.assertIsNone(self.pick())

    def test_follows_series_just_playing_on_same_service(self) -> None:
        self.tp._remember_episode_series("Peacock", ({"id": 2316}, "tv"))
        self.assertEqual(self.pick()["name"], "The Office")
        # Another service's history does not carry over.
        self.assertIsNone(self.pick(service="Hulu"))

    def test_history_expires(self) -> None:
        self.tp._remember_episode_series("Peacock", ({"id": 2316}, "tv"))
        later = mock.patch.object(
            self.tp.time, "monotonic", return_value=self.tp.time.monotonic() + 5 * 3600
        )
        with later:
            self.assertIsNone(self.pick())

    def test_episode_series_hit_is_flagged_without_mutating_search_row(self) -> None:
        row = {"id": 2316, "name": "The Office"}
        item, kind = self.tp._mark_episode_series((row, "tv"))
        self.assertTrue(item[self.tp.EPISODE_SERIES_FLAG])
        self.assertEqual(kind, "tv")
        self.assertNotIn(self.tp.EPISODE_SERIES_FLAG, row)
        self.assertEqual(self.tp._mark_episode_series((None, None)), (None, None))

    def _pick_from(self, cands: list[dict]):
        return self.tp._pick_wikidata_episode_series(cands, service="Peacock", providers=frozenset({386}))

    def test_only_candidate_on_service_wins(self) -> None:
        cands = [{"name": "The Office", "tmdb_tv_id": 2316}, {"name": "ER", "tmdb_tv_id": 4588}]
        self.assertEqual(self._pick_from(cands)["name"], "The Office")

    def test_candidate_without_tmdb_id_keeps_it_unresolved(self) -> None:
        # The id-less series could also be on Peacock; don't guess.
        cands = [{"name": "The Office", "tmdb_tv_id": 2316}, {"name": "Some Sitcom", "tmdb_tv_id": None}]
        self.assertIsNone(self._pick_from(cands))

    def test_failed_provider_lookup_keeps_it_unresolved(self) -> None:
        self.providers_by_id[4588] = None
        cands = [{"name": "The Office", "tmdb_tv_id": 2316}, {"name": "ER", "tmdb_tv_id": 4588}]
        self.assertIsNone(self._pick_from(cands))

    def test_id_less_candidate_still_yields_to_recent_series(self) -> None:
        self.tp._remember_episode_series("Peacock", ({"id": 2316}, "tv"))
        cands = [{"name": "The Office", "tmdb_tv_id": 2316}, {"name": "Some Sitcom", "tmdb_tv_id": None}]
        self.assertEqual(self._pick_from(cands)["name"], "The Office")


if __name__ == "__main__":
    unittest.main()
