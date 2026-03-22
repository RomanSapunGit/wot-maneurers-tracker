"""
Tankopedia helpers — fetches vehicle tag/name mappings from the WoT API.
"""

import urllib.request
import urllib.parse
import json

from .constants import REALM_URLS


def fetch_tag_to_name(
    app_id: str,
    realm: str,
    tier: int = 10,
    progress_cb=None,
) -> tuple[dict[str, dict], dict[int, dict]]:
    """
    Fetches all vehicles (optionally filtered by tier) from the WoT encyclopedia.
    Returns (tag_to_info_dict, tank_id_to_name).
    tag_to_info_dict format: { 'tag': {'name': str, 'short_name': str} }
    """
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])
    tag_to_name: dict[str, dict] = {}
    tank_id_to_name: dict[int, dict] = {}
    page = 1
    while True:
        enc = {
            "application_id": app_id,
            "fields": "tag,name,short_name,tank_id,nation,tier",
            "page_no": page,
            "limit": 100,
        }
        if tier and tier > 0:
            enc["tier"] = tier
        params = urllib.parse.urlencode(enc)
        url = f"{base_url}/wot/encyclopedia/vehicles/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            if progress_cb:
                progress_cb(f"[!] Tankopedia fetch error: {e}")
            break
        if data.get("status") != "ok":
            if progress_cb:
                progress_cb(f"[!] Tankopedia API error: {data.get('error', data)}")
            break
        for _, info in data["data"].items():
            if isinstance(info, dict) and "tag" in info and "name" in info:
                nation = info.get("nation", "unknown")
                full_tag = f"{nation}:{info['tag']}"
                tag_to_name[full_tag] = {
                    "name": info["name"],
                    "short_name": info.get("short_name", info["name"])
                }
                if "tank_id" in info:
                    tank_id_to_name[info["tank_id"]] = {
                        "name": info["name"],
                        "tier": info.get("tier", 0)
                    }
        meta = data.get("meta", {})
        total_pages = meta.get("page_total", 1)
        if progress_cb:
            progress_cb(f"Tankopedia: page {page}/{total_pages} ({len(tag_to_name)} tanks)")
        if page >= total_pages:
            break
        page += 1
    return tag_to_name, tank_id_to_name


def resolve_vehicle_name(vehicle_type: str, tag_to_name: dict[str, dict]) -> str | None:
    tag = vehicle_type.split(":", 1)[-1]
    # We need to find the tag in the dict keys
    for full_tag, info in tag_to_name.items():
        if full_tag.endswith(":" + tag) or full_tag == tag:
            return info["name"]
    return None
