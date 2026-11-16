# -*- coding: utf-8 -*-
import unittest

from wisland.services.netease import NeteaseLog


def _play_line(song_id: str, title: str = "下一首") -> str:
    return (
        '[100:200:1116/120000:123456:INFO:app.cpp(1)] '
        '【playing】,"playOneTrackInPlayingList",'
        '{"track":{"id":"' + song_id + '","name":"' + title + '",'
        '"duration":180000,"artists":[{"name":"歌手"}],'
        '"album":{"name":"专辑","picUrl":""}}}'
    )


class NeteaseLikedStateTests(unittest.TestCase):
    def setUp(self):
        self.log = NeteaseLog(path="missing.elog")
        self.log.track = {"id": "1", "title": "上一首"}
        self.log.liked = True

    def test_new_unknown_track_does_not_inherit_previous_like(self):
        self.log._line(_play_line("2"))
        self.assertEqual(self.log.track["id"], "2")
        self.assertFalse(self.log.liked)

    def test_tray_icon_immediately_after_track_change_sets_state(self):
        self.log._line(_play_line("2"))
        self.log._line('[100:200:1116/120001:123457:INFO:x(1)] {"id":"trayLike","icon":"/liked.svg"}')
        self.assertTrue(self.log.liked)
        self.assertTrue(self.log._liked_by_id["2"])

    def test_late_tray_icon_event_is_ignored(self):
        self.log._line(_play_line("2"))
        self.log._line('[100:200:1116/120004:126000:INFO:x(1)] {"id":"trayLike","icon":"/liked.svg"}')
        self.assertFalse(self.log.liked)

    def test_is_heart_telemetry_is_not_treated_as_like_state(self):
        self.log._line(_play_line("2"))
        self.log._line('[100:200:1116/120001:123457:INFO:x(1)] {"id":"2","is_heart":1}')
        self.assertFalse(self.log.liked)

    def test_add_and_delete_track_events_update_matching_song(self):
        self.log._line(_play_line("2"))
        self.log._line('[100:200:1116/120001:123457:INFO:x(1)] {"op":"add_track","ids":[2]}')
        self.assertTrue(self.log.liked)
        self.log._line('[100:200:1116/120002:123458:INFO:x(1)] {"op":"del_track","ids":[2]}')
        self.assertFalse(self.log.liked)

    def test_wisland_like_action_updates_parser_cache(self):
        self.log._line(_play_line("2"))
        self.log.set_liked("2", True)
        self.assertTrue(self.log.liked)
        self.assertTrue(self.log._liked_by_id["2"])


if __name__ == "__main__":
    unittest.main()
