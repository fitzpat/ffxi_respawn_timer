#!/usr/bin/env python3
"""Build a candidate tag database from an LSB checkout and reviewed supplements.

Requires PyYAML only for this maintenance command, not for the timer app.
Writes mob_tags.generated.json by default so manual edits are never overwritten.
"""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LSB_REF = "1450874235d41341a2ced74c1dbbe9e4477611d2"


def canonical(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def apply_classic_timings(mobs, reference):
    """Apply the audited era profile after ID supplements, never NM cooldowns."""
    for mid, entry in mobs.items():
        timing = reference["mobs"].get(mid)
        entry["timing_profile"] = "classic_75"
        if timing is None:
            entry["respawn_seconds"] = None
            entry["timing_basis"] = "unreviewed"
            entry["timer_source"] = "No audited classic timing; use a manual override"
            continue
        entry["respawn_seconds"] = timing["respawn_seconds"]
        entry["timing_basis"] = timing["basis"]
        entry["timer_source"] = timing["source"]
        entry["timing_note"] = timing["note"]
        entry["classic_level_range"] = [timing["source_record"]["min_level"], timing["source_record"]["max_level"]]
        if timing["source"] not in entry["sources"]:
            entry["sources"].append(timing["source"])


def build(zones, supplements, wiki_names, ref=LSB_REF, classic_timings=None):
    wiki_lookup = {canonical(n): n for n in wiki_names}
    mobs, catalog, spawn_lookup, sources = {}, {}, {}, []

    def add(ph, nm, source, note=None):
        ph = str(ph)
        spawn = spawn_lookup[ph]
        entry = mobs.setdefault(ph, {
            "name": spawn["name"], "zone": spawn["zone"],
            "placeholder_for": [], "respawn_seconds": spawn["respawn_seconds"],
            "despawn_seconds": 20, "tags": [], "sources": [],
            "timer_source": "LSB respawn delay; 20-second corpse allowance per configured HorizonXI timing rule",
        })
        if nm not in entry["placeholder_for"]:
            entry["placeholder_for"].append(nm)
        if source not in entry["sources"]:
            entry["sources"].append(source)
        if note and note not in entry.setdefault("notes", []):
            entry["notes"].append(note)

    for zone in zones:
        d, zone_name = zone["data"], zone["zone"]
        url = f"https://github.com/LandSandBoat/server/blob/{ref}/data/zones/{zone_name}/mobs.yaml"
        sources.append({"zone": zone_name, "url": url, "sha256": zone.get("sha256")})
        templates = d.get("templates", {})
        spawns = {int(i): s for i, s in d.get("spawns", {}).items()}
        for mid, s in spawns.items():
            template_name = s.get("template", s.get("script", ""))
            template = templates.get(template_name, {})
            name = template.get("display_name", template_name).split("_[")[0]
            name = wiki_lookup.get(canonical(name), name.replace("_", " "))
            respawn = s.get("attributes", {}).get("spawn", {}).get(
                "respawn", template.get("attributes", {}).get("spawn", {}).get("respawn")
            )
            spawn_lookup[str(mid)] = {"name": name, "zone": zone_name, "respawn_seconds": respawn}
            if "notorious" in template.get("type", []) or canonical(name) in wiki_lookup:
                record = catalog.setdefault((zone_name, name), {"zone": zone_name, "name": name, "mob_ids": []})
                record["mob_ids"].append(mid)
        for slot in d.get("slots", []):
            members = {int(i): p for i, p in slot["members"].items()}
            targets = []
            for mid, params in members.items():
                s = spawns.get(mid, {})
                t = templates.get(s.get("template", ""), {})
                if "notorious" in t.get("type", []) and "chance" in params:
                    targets.append(mid)
            # These three NMs and Balloon share a uniform lottery slot.
            if zone_name == "outer_horutoto_ruins":
                targets.extend(mid for mid in members if spawns.get(mid, {}).get("template") in (
                    "Bomb_King", "Doppelganger_Dio", "Doppelganger_Gog"
                ))
            for ph, params in members.items():
                if ph in targets and zone_name != "outer_horutoto_ruins":
                    continue
                if "chance" in params:
                    continue
                for nm in targets:
                    if ph != nm and ph in spawns:
                        add(ph, spawn_lookup[str(nm)]["name"], url)

    for rule in supplements:
        nm, zone = rule["nm"], rule["zone"]
        if rule.get("replace_lsb"):
            for mid in list(mobs):
                entry = mobs[mid]
                if entry["zone"] == zone:
                    entry["placeholder_for"] = [n for n in entry["placeholder_for"] if canonical(n) != canonical(nm)]
                    if not entry["placeholder_for"]:
                        del mobs[mid]
        ids = rule.get("placeholder_ids")
        if ids is None:
            ids = [int(i) for i, e in mobs.items() if e["zone"] == zone and any(
                canonical(n) == canonical(nm) for n in e["placeholder_for"]
            )]
        for ph in ids:
            if str(ph) not in spawn_lookup:
                raise ValueError(f"{nm}: unknown full placeholder ID {ph}")
            if spawn_lookup[str(ph)]["zone"] != zone:
                raise ValueError(f"{nm}: placeholder {ph} is in another zone")
            add(ph, nm, rule["source"], rule.get("note"))
            if "respawn_seconds" in rule:
                mobs[str(ph)]["respawn_seconds"] = rule["respawn_seconds"]
                mobs[str(ph)]["despawn_seconds"] = rule.get("despawn_seconds", 20)
                mobs[str(ph)]["timer_source"] = rule["source"]

    if classic_timings is not None:
        apply_classic_timings(mobs, classic_timings)
    mapped = {canonical(n) for e in mobs.values() for n in e["placeholder_for"]}
    for entry in mobs.values():
        entry["placeholder_for"].sort()
    db = {
        "version": 1,
        "description": "Full decimal mob ID -> NM placeholder tags. Edit placeholder_for, respawn_seconds, despawn_seconds, and tags; the app reloads saved edits.",
        "generated_on": date.today().isoformat(),
        "lsb_revision": ref,
        "timing_profile": "classic_75" if classic_timings is not None else "source",
        "coverage": {
            "lsb_zone_files": len(zones), "lsb_nm_records": len(catalog),
            "placeholder_ids": len(mobs), "tagged_nm_names": len(mapped),
            "horizon_lottery_category_names": len(wiki_names),
            "horizon_lottery_names_without_mapping": [n for n in wiki_names if canonical(n) not in mapped],
        },
        "notes": [
            "LSB mappings are candidates for HorizonXI, not a guarantee of identical server behavior.",
            "Reviewed Horizon wiki supplements supply placeholder IDs; the classic_75 timing profile takes precedence over their modern or server-specific timer values.",
            "respawn_seconds is the PH respawn delay, never the NM lottery cooldown. despawn_seconds defaults to 20 seconds from defeat to disappearance; the auto Override adds both.",
            "Some NMs are timed, forced, or scripted and have no lottery placeholder. Main Horizon NM category pagination was inaccessible; the 150-entry lottery category was reviewed.",
            "Classic baseline timings are inferred from zone type and era level bands unless an individual exception is documented. Check timing_basis and timing_note; these are not all individually measured timers.",
        ],
        "mobs": dict(sorted(mobs.items(), key=lambda p: int(p[0]))),
    }
    report = {"lsb_revision": ref, "zone_sources": sources, "notorious_monsters": []}
    for (zone, name), entry in sorted(catalog.items()):
        entry["placeholder_ids"] = [int(i) for i, e in mobs.items() if e["zone"] == zone and any(canonical(n) == canonical(name) for n in e["placeholder_for"])]
        entry["status"] = "placeholder mapped" if entry["placeholder_ids"] else "no placeholder mapping; may be timed, forced, or scripted"
        report["notorious_monsters"].append(entry)
    return db, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--lsb-root", type=Path, help="LandSandBoat server checkout (data/zones layout)")
    src.add_argument("--snapshot", type=Path, help="JSON array of fetched zone/content records")
    parser.add_argument("--output", type=Path, default=ROOT / "mob_tags.generated.json")
    parser.add_argument("--report", type=Path, default=ROOT / "data/nm_scan_report.json")
    parser.add_argument("--ref", default=LSB_REF, help="LSB commit SHA used for source links")
    args = parser.parse_args()
    import yaml
    if args.snapshot:
        raw = json.loads(args.snapshot.read_text(encoding="utf-8"))
    else:
        raw = [{"zone": p.parent.name, "content": p.read_text(encoding="utf-8")} for p in sorted((args.lsb_root / "data/zones").glob("*/mobs.yaml"))]
    zones = [{"zone": z["zone"], "sha256": hashlib.sha256(z["content"].encode()).hexdigest(), "data": yaml.load(z["content"], Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))} for z in raw]
    supplements = json.loads((ROOT / "data/placeholder_supplements.json").read_text(encoding="utf-8"))
    names = json.loads((ROOT / "data/horizon_lottery_names.json").read_text(encoding="utf-8"))
    classic = json.loads((ROOT / "data/classic_timing_reference.json").read_text(encoding="utf-8"))
    db, report = build(zones, supplements, names, args.ref, classic_timings=classic)
    for path, value in ((args.output, db), (args.report, report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(db["coverage"], indent=2))


if __name__ == "__main__":
    main()
