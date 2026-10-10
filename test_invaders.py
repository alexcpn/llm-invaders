"""python3 -m unittest -v test_invaders"""

import os
import tempfile
import unittest

from invaders.agents import AlwaysFire, Autopilot, Agent
from invaders.budget import BudgetExceeded, Ledger
from invaders.engine import Game, Params
from invaders.harness import play


class EngineTests(unittest.TestCase):
    def test_a_shot_kills_the_alien_above(self):
        g = Game(seed=1)
        x, y = max(g.aliens, key=lambda a: a[1])
        g.x = x
        g.act("fire")
        for _ in range(100):
            g.advance(0.02)
            if g.kills:
                break
        self.assertEqual(g.kills, 1)

    def test_killing_the_last_alien_mid_tick_wins_without_crashing(self):
        g = Game(seed=2)
        g.aliens = {(g.x, 5)}
        g.act("fire")
        g.advance(2.0)
        self.assertTrue(g.won)
        self.assertEqual(g.reason, "cleared the wave")

    def test_the_wave_lands_if_nobody_shoots(self):
        r = play(_Wait(), seed=3)
        self.assertFalse(r["won"])
        self.assertIn(r["reason"], ("the aliens landed", "out of lives"))

    def test_describe_lists_the_facts_a_player_needs(self):
        text = Game(seed=4).describe()
        for words in ("Your cannon", "shot", "Alien directly above you", "Nearest alien column", "Bombs near you", "Lives"):
            self.assertIn(words, text)


class _Wait(Agent):
    name = "wait"

    def act(self, game):
        return "wait"


class HarnessTests(unittest.TestCase):
    def test_a_fast_autopilot_wins_and_firing_blindly_does_not(self):
        self.assertTrue(all(play(Autopilot(), seed=s)["won"] for s in range(5)))
        self.assertFalse(any(play(AlwaysFire(), seed=s)["won"] for s in range(5)))

    def test_latency_is_charged_in_game_time(self):
        slow = play(Autopilot(), seed=0, fixed_latency=1.0, speed=0.2)
        self.assertAlmostEqual(slow["mean_game_s_per_decision"], 0.2, places=3)

    def test_the_same_seed_replays_the_same_game(self):
        a, b = play(Autopilot(), seed=7), play(Autopilot(), seed=7)
        a.pop("wall_seconds"); b.pop("wall_seconds")
        self.assertEqual(a, b)


class BudgetTests(unittest.TestCase):
    def test_paid_calls_stop_before_the_limit(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = Ledger(os.path.join(d, "ledger.json"), stop_at_usd=0.01)
            ledger.record("m", 0.006, 0.5)
            ledger.check()
            ledger.record("m", 0.006, 0.5)
            with self.assertRaises(BudgetExceeded):
                ledger.check()
            ledger.save()
            self.assertAlmostEqual(Ledger(os.path.join(d, "ledger.json")).spent, 0.012)


if __name__ == "__main__":
    unittest.main()
