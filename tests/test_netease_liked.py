# -*- coding: utf-8 -*-
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

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

    def test_consecutive_liked_tracks_use_library_without_a_tray_update(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "Library").mkdir()
            with closing(sqlite3.connect(base / "Library" / "webdb.dat")) as db:
                db.execute("CREATE TABLE persistentModel (uniKey TEXT PRIMARY KEY, jsonStr TEXT)")
                db.execute("INSERT INTO persistentModel VALUES (?, ?)",
                           ("async:hostResource", json.dumps({"data": {"likeTrackIds": ["2", "3"]}})))
                db.commit()

                log = NeteaseLog(path=str(base / "cloudmusic.elog"))
                with patch.object(log, "_ensure_meta"), patch("wisland.services.netease.psutil.pid_exists", return_value=True):
                    for sid in ("2", "3", "4"):
                        log._line(_play_line(sid))
                        snap = log.snapshot()
                        self.assertEqual(snap["song_id"], sid)
                        self.assertEqual(snap["liked"], sid in ("2", "3"))

                    log._line(_play_line("3"))
                    log.set_liked("3", False)
                    self.assertFalse(log.snapshot()["liked"])
                    db.execute("UPDATE persistentModel SET jsonStr = ?",
                               (json.dumps({"data": {"likeTrackIds": ["2", "3", "4"]}}),))
                    db.commit()
                    log._next_library_check = 0
                    log._line(_play_line("4"))
                    self.assertTrue(log.snapshot()["liked"])
                    log._line(_play_line("3"))
                    self.assertFalse(log.snapshot()["liked"])

    def test_load_completion_starts_track_prepared_by_privilege_check(self):
        self.log._line(_play_line("2").replace("playOneTrackInPlayingList", "checkPlayPrivilege"))
        self.assertFalse(self.log.playing)
        self.log._line('[100:200:1116/120001:123457:INFO:x(1)] '
                       '【playing】,"native播放资源load完成，开始播放",{"songId":"2"}')
        self.assertTrue(self.log.playing)


if __name__ == "__main__":
    unittest.main()
