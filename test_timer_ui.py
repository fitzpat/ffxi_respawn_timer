"""Timer overview boundaries; runs without Tk or a display."""
from types import SimpleNamespace
import unittest

from timer_ui import matches_timer_filter


class TestTimerOverview(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.untimed = SimpleNamespace(end_at=None)
        self.overdue = SimpleNamespace(end_at=900)
        self.due = SimpleNamespace(end_at=1000)
        self.soon = SimpleNamespace(end_at=1020)
        self.later = SimpleNamespace(end_at=1200)
        self.rows = [self.untimed, self.later, self.overdue, self.soon, self.due]

    def test_due_and_upcoming_filters_partition_timed_mobs_at_deadline(self):
        due = [r for r in self.rows if matches_timer_filter(r, 'Due now', self.now)]
        upcoming = [r for r in self.rows if matches_timer_filter(r, 'Upcoming', self.now)]
        self.assertEqual(due, [self.overdue, self.due])
        self.assertEqual(upcoming, [self.later, self.soon])

    def test_untimed_remains_discoverable_without_counting_as_due(self):
        self.assertEqual([r for r in self.rows if matches_timer_filter(r, 'Untimed', self.now)],
                         [self.untimed])

    def test_timers_includes_every_tracked_state(self):
        self.assertTrue(all(matches_timer_filter(r, 'Timers', self.now) for r in self.rows))

    def test_untracked_is_excluded_from_every_active_filter(self):
        for state in self.rows:
            untracked = SimpleNamespace(end_at=state.end_at, tracked=False)
            for selection in ('Timers', 'Upcoming', 'Due now', 'Untimed'):
                with self.subTest(end_at=state.end_at, selection=selection):
                    self.assertFalse(matches_timer_filter(untracked, selection, self.now))
            self.assertTrue(matches_timer_filter(untracked, 'Untracked', self.now))
            self.assertFalse(matches_timer_filter(state, 'Untracked', self.now))


if __name__ == '__main__':
    unittest.main()
