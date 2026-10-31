"""Tests for the kill-line parser and LogWatcher (run: python -m unittest -v)."""

import os
import queue
import tempfile
import time
import unittest

from ffxi_mob_timer import KILL_RE, MOBID_RE, LogWatcher, parse_minutes


def mob_from(line):
    m = KILL_RE.match(line)
    return m.group(3).strip() if m else None


class TestKillRegex(unittest.TestCase):
    def test_normal_mob(self):
        line = "[08:13:58] Morrowindislong defeats the Buffalo.\r"
        self.assertEqual(mob_from(line), "Buffalo")

    def test_notorious_monster_no_the(self):
        self.assertEqual(mob_from("[21:38:12] Chronus defeats Kirin."), "Kirin")
        self.assertEqual(
            mob_from("[00:39:15] Morrowindislong defeats Mythril Mouth Monamaq."),
            "Mythril Mouth Monamaq",
        )

    def test_the_inside_name_kept(self):
        self.assertEqual(
            mob_from("[00:12:42] Sameowrai defeats Kirlirger the Abhorrent."),
            "Kirlirger the Abhorrent",
        )

    def test_trailing_space_before_period(self):
        self.assertEqual(
            mob_from("[07:31:16] Asclepius defeats Humnox Drumbelly ."),
            "Humnox Drumbelly",
        )

    def test_apostrophe_and_hyphen_names(self):
        self.assertEqual(
            mob_from("[21:52:20] Odiebee defeats Woodnix's Slime."),
            "Woodnix's Slime",
        )
        self.assertEqual(
            mob_from("[22:04:17] Garuda defeats Neo-Ultima."), "Neo-Ultima"
        )

    def test_avatar_killer(self):
        self.assertEqual(
            mob_from("[07:31:20] Ifrit defeats Morgmox Moldnoggin."),
            "Morgmox Moldnoggin",
        )

    def test_no_trailing_period(self):
        self.assertEqual(mob_from("[21:33:50] Jimi defeats Kirin"), "Kirin")

    def test_chat_lines_rejected(self):
        # linkshell chat: "[1]<Sailor>" isn't a bare alnum name
        self.assertIsNone(
            mob_from(
                "[03:34:42] [1]<Sailor> is that where van damme defeats raul julia?"
            )
        )
        # say/tell style "<Name> ..." or "Name : ..." can't match
        self.assertIsNone(
            mob_from("[12:00:00] <Bob> defeats the lizard")
        )
        self.assertIsNone(
            mob_from("[12:00:00] Bob : defeats the lizard")
        )
        # NPC dialogue "Moogle : ..." style
        self.assertIsNone(
            mob_from("[18:10:14] Moogle : I'll look after your items, kupo!")
        )

    def test_mob_killing_player_rejected(self):
        # mobs act as "The X" in logs, which can never match
        self.assertIsNone(
            mob_from("[12:00:00] The Buffalo defeats Morrowindislong.")
        )

    def test_non_kill_lines(self):
        self.assertIsNone(
            mob_from("[08:13:33] Morrowindislong hits the Buffalo for 38 points of damage.")
        )
        self.assertIsNone(mob_from(""))
        self.assertIsNone(mob_from("[08:13:33]"))

    def test_mobid_line_not_a_normal_kill(self):
        # in name mode the addon's own line must not match KILL_RE
        self.assertIsNone(
            mob_from(
                "[08:42:26] [mobid] Morrowindislong defeats Buffalo | id: 16798052 | "
                "hex: 0x01005164 | idx: 356"
            )
        )


class TestMobidRegex(unittest.TestCase):
    LINE = (
        "[08:42:26] [mobid] Morrowindislong defeats Buffalo | id: 16798052 | "
        "hex: 0x01005164 | idx: 356"
    )

    def test_mobid_line(self):
        m = MOBID_RE.match(self.LINE)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2).strip(), "Buffalo")  # mob name
        self.assertEqual(m.group(3), "16798052")         # decimal id
        self.assertEqual(m.group(4), "0x01005164")       # hex id
        self.assertEqual(m.group(5), "356")              # zone index

    def test_other_players_kill(self):
        m = MOBID_RE.match(
            "[21:35:09] [mobid] Odiebee defeats Stringes | id: 16909060 | "
            "hex: 0x01020304 | idx: 772"
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2).strip(), "Stringes")

    def test_plain_defeat_does_not_match_mobid(self):
        self.assertIsNone(
            MOBID_RE.match("[08:42:26] Morrowindislong defeats the Buffalo.")
        )


class TestParseMinutes(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_minutes("16.5"), 16.5)
        self.assertEqual(parse_minutes("2"), 2.0)
        self.assertEqual(parse_minutes(" 21 "), 21.0)

    def test_invalid(self):
        self.assertIsNone(parse_minutes(""))
        self.assertIsNone(parse_minutes("abc"))
        self.assertIsNone(parse_minutes("0"))
        self.assertIsNone(parse_minutes("-5"))
        self.assertIsNone(parse_minutes("16:30"))  # minutes only, per spec


class TestLogWatcher(unittest.TestCase):
    def _collect(self, q, timeout=6.0):
        got = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                got.append(q.get(timeout=0.2))
            except queue.Empty:
                pass
        return got

    def test_tails_newest_file_and_follows_rollover(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "Char_2026.10.15.log")
            b = os.path.join(d, "Char_2026.10.16.log")

            # older file, with a kill already in it (history is skipped)
            with open(a, "w") as f:
                f.write("[00:00:01] Old kills.\r\n")
                f.write("[00:00:02] Someone defeats the Old Mob.\r\n")

            q = queue.Queue()
            w = LogWatcher(lambda: d, q)
            w.start()
            try:
                # give the watcher a couple of polls to attach to a.log
                evs = self._collect(q, timeout=1.6)
                self.assertIn(("watching", "Char_2026.10.15.log"), evs)
                self.assertFalse(
                    any(e[0] == "kill" for e in evs),
                    "must not replay pre-existing lines",
                )

                # append a kill to the file being updated -> detected
                with open(a, "a") as f:
                    f.write("[08:00:00] Morrowindislong defeats the Buffalo.\r\n")
                evs = self._collect(q, timeout=2.0)
                self.assertIn(("kill", "Buffalo", "Buffalo", "08:00:00"), evs)

                # game rolls over to a new log -> watcher follows it
                with open(b, "w") as f:
                    f.write("[08:01:00] New day.\r\n")
                # force a strictly newer mtime in case fs granularity bites
                os.utime(b, (time.time() + 2, time.time() + 2))
                evs = self._collect(q, timeout=2.0)
                self.assertIn(("watching", "Char_2026.10.16.log"), evs)

                with open(b, "a") as f:
                    f.write("[08:02:00] Chronus defeats Kirin.\r\n")
                evs = self._collect(q, timeout=2.0)
                self.assertIn(("kill", "Kirin", "Kirin", "08:02:00"), evs)

                # kills on the stale file are ignored
                with open(a, "a") as f:
                    f.write("[08:03:00] Someone defeats the Stale Mob.\r\n")
                evs = self._collect(q, timeout=1.6)
                self.assertNotIn(
                    ("kill", "Stale Mob", "Stale Mob", "08:03:00"),
                    [e for e in evs if e[0] == "kill"],
                )
            finally:
                w.stop()

    def test_mobid_mode_uses_addon_lines(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "Char_2026.10.16.log")
            with open(a, "w") as f:
                f.write("[00:00:01] Old kills.\r\n")

            q = queue.Queue()
            w = LogWatcher(lambda: d, q, mobid_getter=lambda: True)
            w.start()
            try:
                self._collect(q, timeout=1.6)  # let it attach

                with open(a, "a") as f:
                    # normal kill line: ignored in mobid mode
                    f.write("[08:42:26] Morrowindislong defeats the Buffalo.\r\n")
                    # addon line: keyed by mob id
                    f.write(
                        "[08:42:26] [mobid] Morrowindislong defeats Buffalo | "
                        "id: 16798052 | hex: 0x01005164 | idx: 356\r\n"
                    )
                evs = self._collect(q, timeout=2.0)
                kills = [e for e in evs if e[0] == "kill"]
                self.assertEqual(
                    kills,
                    [("kill", "16798052", "Buffalo [0x01005164 (8052)]", "08:42:26")],
                )
            finally:
                w.stop()

    def test_empty_dir_reports_nothing_watched(self):
        with tempfile.TemporaryDirectory() as d:
            q = queue.Queue()
            w = LogWatcher(lambda: d, q)
            w.start()
            try:
                evs = self._collect(q, timeout=1.6)
                self.assertIn(("watching", None), evs)
            finally:
                w.stop()

    def test_ignores_non_log_files(self):
        with tempfile.TemporaryDirectory() as d:
            swp = os.path.join(d, ".Hidden_2026.10.16.log.swp")
            with open(swp, "w") as f:
                f.write("junk")
            q = queue.Queue()
            w = LogWatcher(lambda: d, q)
            w.start()
            try:
                evs = self._collect(q, timeout=1.6)
                self.assertIn(("watching", None), evs)
            finally:
                w.stop()


if __name__ == "__main__":
    unittest.main()
