"""Verify source extraction with the public spawn-slot data shapes."""

import unittest

from tools.build_mob_tags import build


def source_zone():
    return {"zone": "sample", "data": {
        "templates": {
            "Normal_Mob": {"attributes": {"spawn": {"respawn": 300}}},
            "Rare_Mob": {"type": ["notorious"]},
        },
        "spawns": {"10000001": {"template": "Normal_Mob"},
                   "10000002": {"template": "Normal_Mob"},
                   "10000003": {"template": "Rare_Mob"}},
        "slots": [{"members": {"10000001": {}, "10000003": {"chance": 15, "cooldown": 7200}}}],
    }}


class TestImport(unittest.TestCase):
    def test_only_explicit_ph_slot_is_tagged_and_cooldown_is_not_timer(self):
        db, report = build([source_zone()], [], ["Rare Mob"])
        self.assertEqual(set(db["mobs"]), {"10000001"})
        self.assertEqual(db["mobs"]["10000001"]["respawn_seconds"], 300)
        self.assertEqual(db["mobs"]["10000001"]["despawn_seconds"], 20)
        self.assertEqual(report["notorious_monsters"][0]["placeholder_ids"], [10000001])

    def test_horizon_correction_replaces_lsb_ph_and_preserves_timer(self):
        db, _ = build([source_zone()], [{
            "nm": "Rare Mob", "zone": "sample", "placeholder_ids": [10000002],
            "replace_lsb": True, "respawn_seconds": 960, "source": "wiki reference",
        }], ["Rare Mob"])
        self.assertEqual(set(db["mobs"]), {"10000002"})
        self.assertEqual(db["mobs"]["10000002"]["respawn_seconds"], 960)
        self.assertEqual(db["mobs"]["10000002"]["despawn_seconds"], 20)

    def test_explicit_corpse_delay_remains_editable(self):
        db, _ = build([source_zone()], [{
            "nm": "Rare Mob", "zone": "sample", "placeholder_ids": [10000002],
            "replace_lsb": True, "respawn_seconds": 980, "despawn_seconds": 0,
            "source": "custom timer already includes corpse delay",
        }], ["Rare Mob"])
        self.assertEqual(db["mobs"]["10000002"]["respawn_seconds"], 980)
        self.assertEqual(db["mobs"]["10000002"]["despawn_seconds"], 0)

    def test_unknown_placeholder_id_is_never_generated(self):
        with self.assertRaisesRegex(ValueError, "unknown full placeholder"):
            build([source_zone()], [{"nm": "Rare Mob", "zone": "sample", "placeholder_ids": [99999999], "source": "wiki reference"}], ["Rare Mob"])

    def test_uniform_three_nm_slot_tags_each_other_but_not_itself(self):
        z = source_zone()
        z["zone"] = "outer_horutoto_ruins"
        for mid, name in ((10000003, "Bomb_King"), (10000004, "Doppelganger_Dio"), (10000005, "Doppelganger_Gog")):
            z["data"]["templates"][name] = {"type": ["notorious"]}
            z["data"]["spawns"][mid] = {"template": name}
        del z["data"]["spawns"]["10000003"]
        z["data"]["slots"] = [{"members": {i: {} for i in (10000001, 10000003, 10000004, 10000005)}}]
        db, _ = build([z], [], ["Bomb King", "Doppelganger Dio", "Doppelganger Gog"])
        self.assertEqual(len(db["mobs"]["10000001"]["placeholder_for"]), 3)
        self.assertEqual(db["mobs"]["10000003"]["placeholder_for"], ["Doppelganger Dio", "Doppelganger Gog"])


if __name__ == "__main__":
    unittest.main()
