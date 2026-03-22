"""
Replay parsing — reads .wotreplay binary files and scans directories for destruction events.
"""

import struct
import json
import time
import sys
from pathlib import Path

from .constants import INCOMPLETE_GRACE_SECONDS
from .tankopedia import resolve_vehicle_info


def parse_replay(path: Path) -> tuple[dict | None, dict | None]:
    try:
        with open(path, "rb") as f:
            data = f.read(12)
            if len(data) < 12:
                return None, None
            _, block_count, block1_size = struct.unpack("<III", data)

            b1_data = f.read(block1_size)
            if len(b1_data) < block1_size:
                return None, None
            try:
                block1 = json.loads(b1_data)
            except json.JSONDecodeError:
                return None, None

            block2 = None
            if block_count >= 2:
                b2_size_data = f.read(4)
                if len(b2_size_data) == 4:
                    block2_size = struct.unpack("<I", b2_size_data)[0]
                    b2_data = f.read(block2_size)
                    if len(b2_data) == block2_size:
                        try:
                            block2 = json.loads(b2_data)
                        except json.JSONDecodeError:
                            pass  # block2 stays None, we still return block1
        return block1, block2
    except Exception as e:
        print(f"[!] Failed to parse replay {path.name}: {e}", file=sys.stderr)
        return None, None


def get_death_label(reason: int) -> str:
    return {-1: "Alive", 0: "Destroyed", 1: "Teamkilled", 2: "Drowned"}.get(
        reason, f"Unknown({reason})"
    )


def scan_replays(
    replays_dir,
    clan_tag,
    tag_to_name,
    already_parsed,
    battle_type_filter,
    record_since=0,
    log_cb=None,
    tier_filter=0,
):
    events = []
    replays = sorted(replays_dir.glob("*.wotreplay"), key=lambda f: f.stat().st_mtime)

    for replay in replays:
        if replay.name in already_parsed:
            continue

        if replay.stat().st_mtime < record_since:
            already_parsed.add(replay.name)
            continue

        block1, block2 = parse_replay(replay)

        if block1 is None:
            age = time.time() - replay.stat().st_mtime
            if age > INCOMPLETE_GRACE_SECONDS:
                print(f"[!] Failed to parse {replay.name} (expired)", file=sys.stderr)
                already_parsed.add(replay.name)
            continue

        battle_type = block1.get("battleType")
        if battle_type_filter is not None and battle_type not in battle_type_filter:
            already_parsed.add(replay.name)
            continue

        if block2 is None:
            age = time.time() - replay.stat().st_mtime
            if age <= INCOMPLETE_GRACE_SECONDS:
                if log_cb:
                    log_cb(f"[~] {replay.name} — in progress, retrying later")
                # Emit pending event for ALL clan members in this battle
                battle_time = block1.get("dateTime", "?")
                map_name    = block1.get("mapDisplayName", block1.get("mapName", "?"))

                for sid, veh in block1.get("vehicles", {}).items():
                    p_name = veh.get("name", "")
                    p_clan = veh.get("clanAbbrev", "")
                    p_veh  = veh.get("vehicleType", "?")

                    if p_name and p_clan.upper() == clan_tag.upper():
                        veh_info = resolve_vehicle_info(p_veh, tag_to_name)
                        if veh_info:
                            if tier_filter > 0 and veh_info.get("tier", 0) != tier_filter:
                                continue
                            events.append({
                                "player":      p_name,
                                "veh_tag":     p_veh,
                                "veh_name":    veh_info["name"],
                                "death_label": "Possibly destroyed",
                                "battle_time": battle_time,
                                "map":         map_name,
                                "pending":     True,
                                "replay_name": replay.name,
                            })
                continue

            # Old incomplete replay — mark ALL clan members as destroyed
            already_parsed.add(replay.name)
            battle_time = block1.get("dateTime", "?")
            map_name    = block1.get("mapDisplayName", block1.get("mapName", "?"))

            found_any = False
            for sid, veh in block1.get("vehicles", {}).items():
                p_name = veh.get("name", "")
                p_clan = veh.get("clanAbbrev", "")
                p_veh  = veh.get("vehicleType", "?")

                if p_name and p_clan.upper() == clan_tag.upper():
                    veh_info = resolve_vehicle_info(p_veh, tag_to_name)
                    if veh_info:
                        if tier_filter > 0 and veh_info.get("tier", 0) != tier_filter:
                            continue
                        found_any = True
                        events.append({
                            "player":      p_name,
                            "veh_tag":     p_veh,
                            "veh_name":    veh_info["name"],
                            "death_label": "Destroyed (left battle)",
                            "battle_time": battle_time,
                            "map":         map_name,
                            "pending":     False,
                            "replay_name": replay.name,
                        })

            if not found_any and log_cb:
                log_cb(f"[✗] {replay.name} — left early, no clan members found, skipping")
            elif found_any and log_cb:
                log_cb(f"[✗] {replay.name} — left early, marking clan members destroyed")
            continue

        already_parsed.add(replay.name)
        battle_time = block1.get("dateTime", "?")
        map_name    = block1.get("mapDisplayName", block1.get("mapName", "?"))

        id_to_veh = {
            sid: {
                "name":    veh.get("name", "?"),
                "clan":    veh.get("clanAbbrev", ""),
                "veh_tag": veh.get("vehicleType", "?"),
            }
            for sid, veh in block1.get("vehicles", {}).items()
        }

        battle_results = block2[0] if isinstance(block2, list) and block2 else (block2 or {})
        b2_vehicles = battle_results.get("vehicles", {})

        common = battle_results.get("common", {})
        winner_team = common.get("winnerTeam", -1)

        owner_team = None
        for sid, veh in block1.get("vehicles", {}).items():
            if veh.get("clanAbbrev", "").upper() == clan_tag.upper():
                owner_team = veh.get("team")
                if owner_team:
                    break

        if not owner_team:
            for session_id, stats_data in b2_vehicles.items():
                stats = (
                    stats_data[0]
                    if isinstance(stats_data, list) and stats_data
                    else (stats_data if isinstance(stats_data, dict) else {})
                )
                info = id_to_veh.get(str(session_id), {})
                if info and info.get("clan", "").upper() == clan_tag.upper():
                    owner_team = stats.get("team")
                    if owner_team:
                        break

        is_defeat = owner_team and winner_team != owner_team

        for session_id, stats_data in b2_vehicles.items():
            stats = (
                stats_data[0]
                if isinstance(stats_data, list) and stats_data
                else (stats_data if isinstance(stats_data, dict) else {})
            )
            info = id_to_veh.get(str(session_id), {})
            if not info or info.get("clan", "").upper() != clan_tag.upper():
                continue

            death_reason = stats.get("deathReason", -1)

            if battle_type == 20 and is_defeat and death_reason == -1:
                death_reason = 0

            if death_reason == -1:
                continue

            veh_info = resolve_vehicle_info(info["veh_tag"], tag_to_name)
            if not veh_info:
                continue
            if tier_filter > 0 and veh_info.get("tier", 0) != tier_filter:
                continue
            events.append({
                "player":      info["name"],
                "veh_tag":     info["veh_tag"],
                "veh_name":    veh_info["name"],
                "death_label": get_death_label(death_reason),
                "battle_time": battle_time,
                "map":         map_name,
                "pending":     False,
                "replay_name": replay.name,
            })

        if log_cb:
            log_cb(f"[✓] {replay.name} — {battle_time}, {map_name}")

    return events, already_parsed
