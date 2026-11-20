import unittest

from desk import stamp
from desk import settings as S
from tests.test_desk import DemoCase


class Stamp(DemoCase):
    def test_hash_follows_rules_and_ignores_the_rest(self):
        a = S.validate({})
        self.assertEqual(stamp.rules_hash(a), stamp.rules_hash(S.validate({"watchlist": ["F"], "paused": True,
                                                                           "est_cost_per_share": 0.05})))
        self.assertNotEqual(stamp.rules_hash(a), stamp.rules_hash(S.validate({"target_r": 3})))
        self.assertEqual(len(stamp.rules_hash(a)), 8)
        self.assertEqual(stamp.skills_commit(), "3d0f4ef")

    def test_every_signal_is_stamped_and_the_rule_set_is_remembered_once(self):
        d = self.desk()
        d.scan()
        sigs = d.j.signals()
        h = stamp.rules_hash(S.load())
        for s in sigs:
            self.assertEqual(s["payload"]["stamp"], {"desk": "1.0.0", "skills": "3d0f4ef", "rules": h}, s["symbol"])
        known = d.j.get("rulesets")
        self.assertEqual(list(known), [h])
        self.assertEqual(known[h]["rules"]["target_r"], 2.0)
        self.assertEqual(known[h]["first_seen"], "2026-10-19 10:15")


class Rule201AndOneShareStamp(unittest.TestCase):
    def test_paper_signals_carry_the_two_new_rules_and_live_does_not(self):
        from desk import settings as S
        self.assertTrue(stamp.rules(S.validate({"mode": "paper"}))["rule201_limit"])
        self.assertTrue(stamp.rules(S.validate({"mode": "paper"}))["one_share_floor"])
        self.assertNotIn("rule201_limit", stamp.rules(S.validate({"mode": "live"})))
