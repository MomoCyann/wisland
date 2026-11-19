import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from wisland.services.game_calendar import BEIJING
from wisland.services.game_daily import Daily, Run, _hsr, _ww, _zzz, daily_reminder


TODAY = datetime(2026, 11, 19, 4, tzinfo=BEIJING)
CHECK_TIME = TODAY + timedelta(minutes=1)


def rows(*lines):
    return [(TODAY + timedelta(minutes=2, seconds=i), line) for i, line in enumerate(lines)]


class DailyRemindersTests(unittest.TestCase):
    def test_alert_waits_until_0401_and_clears_on_completion(self):
        self.assertEqual(daily_reminder(Daily(), CHECK_TIME - timedelta(seconds=1)), "")
        self.assertEqual(daily_reminder(Daily(), CHECK_TIME), "未见运行记录")
        self.assertEqual(daily_reminder(Daily(activity_full=True), CHECK_TIME), "")
        self.assertEqual(daily_reminder(Daily(activity="找不到日志"), CHECK_TIME), "找不到日志")
        self.assertIn("已启动", daily_reminder(Daily(run=Run(started=CHECK_TIME)), CHECK_TIME))

    def test_starrail_requires_full_score(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            log = folder / "20261119-040100-example.log"
            for score in (499, 500):
                log.write_text(f"2026-11-19 04:02:00 | INFO | 当前累计分数：{score}/500", encoding="utf-8")
                stamp = (CHECK_TIME + timedelta(minutes=1, seconds=score)).timestamp()
                os.utime(log, (stamp, stamp))
                result = _hsr(folder, TODAY, Run())
                self.assertEqual(result.activity, f"每日实训 {score}/500")
                self.assertEqual(result.activity_full, score == 500)

    def test_zzz_generic_success_is_not_full_activity(self):
        success = "指令[ 活跃度奖励 ] 执行成功 返回状态 成功"
        incomplete = "指令[ 活跃度奖励 ] 节点 识别活跃度 返回状态 活跃度未满"
        full = "指令[ 活跃度奖励 ] 节点 识别活跃度 返回状态 活跃度已满"
        self.assertFalse(_zzz(rows(incomplete, success), Run()).activity_full)
        self.assertIsNone(_zzz(rows(success), Run()).activity_full)
        self.assertTrue(_zzz(rows(full, success), Run()).activity_full)

    def test_ww_needs_both_finished_flow_and_at_least_180_stamina(self):
        prefix = (
            "TacetTask:info_set Teleport to Tacet Suppression 0",
            "TacetTask:info_set current_stamina 240",
            "BaseWWTask:当前体力大于等于双倍",
            "TacetTask:info_set current_stamina 120",
        )
        finish = "DailyTask:每日任务已完成"
        last_fight = ("BaseWWTask:使用单倍体力", "TacetTask:info_set current_stamina 60")
        low = _ww(rows(*prefix, finish), Run())
        self.assertFalse(low.activity_full)
        self.assertIn("180 波片", daily_reminder(low, CHECK_TIME))
        self.assertIsNone(_ww(rows(*prefix, *last_fight), Run()).activity_full)
        exact = _ww(rows(*prefix, *last_fight, finish), Run())
        self.assertIn("波片 −180", exact.stamina)
        self.assertTrue(exact.activity_full)
        self.assertEqual(daily_reminder(exact, CHECK_TIME), "")
        invalid = _ww(rows(*prefix, "BaseWWTask:使用双倍", "BaseWWTask:current stamina: -1 must_use completed", finish), Run())
        self.assertFalse(invalid.activity_full)
