"""Video-only apps that report ``MediaType.Music`` are treated as video.

HBO Max reported ``Music`` for *Nathan For You*: show in ``artist``, episode in
``title``. Pigeon trusted the label, drew the music layout (zone 4 = song /
artist instead of cast) and searched TMDb for the episode title.
"""

import unittest
from types import SimpleNamespace

try:
    from pyatv.const import DeviceState, MediaType
except Exception:  # pragma: no cover - pyatv missing in this environment
    MediaType = None

from pigeon.streaming_service_badges import is_video_only_streaming_service


def _playing(media_type, *, title="The Movement", artist="Nathan For You"):
    return SimpleNamespace(
        media_type=media_type,
        device_state=DeviceState.Playing,
        title=title,
        artist=artist,
        album=None,
        genre=None,
        series_name=None,
        season_number=None,
        episode_number=None,
        total_time=1320,
        position=300,
        hash="h",
    )


def _atv(app_name, app_id):
    return SimpleNamespace(
        metadata=SimpleNamespace(app=SimpleNamespace(name=app_name, identifier=app_id)),
        power=None,
        audio=None,
    )


class VideoOnlyServiceTests(unittest.TestCase):
    def test_video_services(self) -> None:
        for name, bid in [
            ("HBO Max", "com.wbd.stream"),
            ("Max", ""),
            ("Netflix", "com.netflix.Netflix"),
            ("Disney+", "com.disney.disneyplus"),
            ("Hulu", "com.hulu.plus"),
            ("Prime Video", "com.amazon.aiv.AIVApp"),
        ]:
            self.assertTrue(is_video_only_streaming_service(name, bid), name)

    def test_music_capable_apps_are_not_video_only(self) -> None:
        for name, bid in [
            ("Music", "com.apple.TVMusic"),
            ("Apple Music", ""),
            ("Spotify", "com.spotify.client"),
            ("YouTube", "com.google.ios.youtube"),
            ("TV", "com.apple.TVWatchList"),
            ("", ""),
        ]:
            self.assertFalse(is_video_only_streaming_service(name, bid), name or "(none)")


@unittest.skipIf(MediaType is None, "pyatv not installed")
class MetadataForPlayingTests(unittest.TestCase):
    def _meta(self, media_type, app_name, app_id):
        from pigeon.apple_tv_now_playing import _metadata_for_playing

        return _metadata_for_playing(_atv(app_name, app_id), _playing(media_type))

    def test_hbo_music_label_is_corrected(self) -> None:
        md = self._meta(MediaType.Music, "HBO Max", "com.wbd.stream")
        self.assertEqual(md["media_type"], str(MediaType.Unknown))
        self.assertEqual(md["media_type_reported"], str(MediaType.Music))
        self.assertEqual(md["query"], "Nathan For You")
        self.assertEqual(md["app_name"], "HBO Max")

    def test_hbo_normal_label_untouched(self) -> None:
        md = self._meta(MediaType.Unknown, "HBO Max", "com.wbd.stream")
        self.assertEqual(md["media_type"], str(MediaType.Unknown))
        self.assertNotIn("media_type_reported", md)
        self.assertEqual(md["query"], "Nathan For You")

    def test_real_music_stays_music(self) -> None:
        for app_name, app_id in [("Music", "com.apple.TVMusic"), ("Spotify", "com.spotify.client")]:
            md = self._meta(MediaType.Music, app_name, app_id)
            self.assertEqual(md["media_type"], str(MediaType.Music), app_name)
            self.assertNotIn("media_type_reported", md)


if __name__ == "__main__":
    unittest.main()
