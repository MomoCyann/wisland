# -*- coding: utf-8 -*-
import os
import unittest

from wisland.services.netease import NeteaseLog


class NeteaseFmAndModeTests(unittest.TestCase):
    def setUp(self):
        self.pid = os.getpid()
        self.log = NeteaseLog(path="missing.elog")
        self.log._meta["99999"] = {
            "id": "99999",
            "title": "旧歌",
            "artist": "歌手A",
            "album": "专辑A",
            "duration": 200.0,
            "cover": "https://example.com/old.jpg",
        }

    def test_fm_track_change_uses_smtc_and_updatemenu_hints_without_dropping_session(self):
        p = self.pid
        # 1. Start in AI mode with song 99999
        self.log._line(
            f'[{p}:200:1118/010000:100000:INFO:app.cpp(1)] '
            '【playing】,"playOneTrackInPlayingList",'
            '{"scene":"aiMode","track":{"id":"99999","name":"旧歌","duration":200000,'
            '"artists":[{"name":"歌手A"}],"album":{"name":"专辑A","picUrl":"https://example.com/old.jpg"}}}'
        )
        snap1 = self.log.snapshot()
        self.assertIsNotNone(snap1)
        self.assertEqual(snap1["play_mode"], "ai")
        self.assertEqual(snap1["title"], "旧歌")

        # 2. Switch to FM mode (playFm): NetEase writes fmPlay + UpdateMenu + SMTC title + native start load (no playOneTrackInPlayingList!)
        self.log._line(f'[{p}:200:1118/010005:105000:INFO:app.cpp(1)] 【fmPlaying】,"fmPlay","入口",{{"scene":"fm"}}')
        self.log._line(f'[{p}:200:1118/010005:105010:INFO:app.cpp(1)] 【playing】,"播放模式切换","旧播放模式::","playAi","新播放模式::","playFm"')
        self.log._line(f'[{p}:200:1118/010005:105020:INFO:winhelper.cpp(1)] UpdateMenu:[{{"text":"新歌 - 歌手1/歌手2","menu_id":"openVinylPage"}}]')
        self.log._line(f'[{p}:200:1118/010005:105030:INFO:smtc_wrapper.cpp(1)] [SMTCWrapper] SMTC title=新歌, artist=歌手1')
        # Prevent real network call during test
        self.log._meta_pending.add("88888")
        self.log._line(f'[{p}:200:1118/010005:105040:INFO:app.cpp(1)] 【playing】,"native播放资源开始load",{{"songId":"88888"}}')

        snap2 = self.log.snapshot()
        self.assertIsNotNone(snap2)
        self.assertEqual(snap2["song_id"], "88888")
        self.assertEqual(snap2["title"], "新歌")
        self.assertEqual(snap2["artist"], "歌手1/歌手2")
        self.assertEqual(snap2["play_mode"], "fm")
        self.assertFalse(snap2["meta_ready"])

        # 3. Thumbnail arrives 50ms later, then API meta fills duration & cover URL
        self.log._line(rf'[{p}:200:1118/010005:105090:INFO:smtc_wrapper.cpp(1)] [SMTCWrapper] SMTC thumbnail=C:\fake\thumb.dat')
        snap3 = self.log.snapshot()
        self.assertEqual(snap3["cover_file"], r"C:\fake\thumb.dat")
        self.assertTrue(snap3["meta_ready"])

        self.log._meta_done("88888", {
            "id": "88888",
            "title": "新歌",
            "artist": "歌手1 / 歌手2",
            "album": "新专辑",
            "duration": 240.0,
            "cover": "https://example.com/new.jpg",
        })
        snap4 = self.log.snapshot()
        self.assertEqual(snap4["album"], "新专辑")
        self.assertEqual(snap4["duration"], 240.0)
        self.assertEqual(snap4["cover"], "https://example.com/new.jpg")

    def test_stub_without_hints_keeps_previous_snapshot_briefly_instead_of_returning_none(self):
        p = self.pid
        self.log._line(
            f'[{p}:200:1118/010000:100000:INFO:app.cpp(1)] '
            '【playing】,"playOneTrackInPlayingList",'
            '{"track":{"id":"111","name":"第一首","duration":180000,"artists":[{"name":"A"}],"album":{"name":"X","picUrl":""}}}'
        )
        self.assertIsNotNone(self.log.snapshot())

        # New track starts loading before any title hint is written
        self.log._meta_pending.add("222")
        self.log._line(f'[{p}:200:1118/010010:110000:INFO:app.cpp(1)] 【playing】,"native播放资源load完成，开始播放",{{"songId":"222"}}')
        snap = self.log.snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(snap["title"], "第一首")

    def test_switching_fm_to_ai_ignores_transient_playcycle_mode(self):
        p = self.pid
        self.log._line(
            f'[{p}:200:1118/010000:100000:INFO:app.cpp(1)] '
            '【playing】,"playOneTrackInPlayingList",'
            '{"scene":"fm","track":{"id":"111","name":"漫游曲","duration":180000,"artists":[{"name":"A"}],"album":{"name":"X","picUrl":""}}}'
        )
        self.log.set_play_mode("ai")
        self.log._line(f'[{p}:200:1118/010001:101000:INFO:app.cpp(1)] 【playing】,"播放模式切换","旧播放模式::","playFm","新播放模式::","playCycle"')
        self.assertEqual(self.log.snapshot()["play_mode"], "ai")
        self.log._line(f'[{p}:200:1118/010002:101400:INFO:app.cpp(1)] 【playing】,"心动模式开启成功"')
        self.assertEqual(self.log.snapshot()["play_mode"], "ai")

    def test_preload_traylike_syncs_heart_when_switching_fm_to_ai(self):
        p = self.pid
        self.log._line(f'[{p}:200:1118/010000:100000:INFO:app.cpp(1)] 【fmPlaying】,"fmPlay","入口",{{"scene":"fm"}}')
        self.log._line(f'[{p}:32448:1118/010000:100005:INFO:winhelper.cpp(1)] UpdateMenu:[{{"text":"Old - A","menu_id":"openVinylPage"}}]')
        self.log._meta_pending.add("255227")
        self.log._line(f'[{p}:200:1118/010000:100010:INFO:app.cpp(1)] 【playing】,"native播放资源开始load",{{"songId":"255227"}}')
        self.assertFalse(self.log.snapshot()["liked"])

        # Switch to AI mode where UpdateMenu(openVinylPage + trayLike) precedes native start load by ~78ms
        self.log._line(f'[{p}:32448:1118/010010:110000:INFO:winhelper.cpp(1)] UpdateMenu:[{{"text":"Twisted - Keith Sweat","menu_id":"openVinylPage"}}]')
        self.log._line(
            f'[{p}:32448:1118/010010:110000:INFO:winhelper.cpp(1)] '
            'UpdateMenu:[{"enable":true,"btns":[{"id":"trayLike","url":"normalimage=\\"file=\'orpheus://orpheus/pub/public/assets/svg/menu/liked.svg\'\\""}]}]'
        )
        self.log._meta_pending.add("23518563")
        self.log._line(f'[{p}:1944:1118/010010:110078:INFO:app.cpp(1)] 【playing】,"native播放资源开始load",{{"songId":"23518563"}}')
        snap = self.log.snapshot()
        self.assertEqual(snap["song_id"], "23518563")
        self.assertTrue(snap["liked"])


if __name__ == "__main__":
    unittest.main()
