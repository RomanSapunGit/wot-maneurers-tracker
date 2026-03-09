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
) -> tuple[dict[str, str], dict[int, str]]:
    """
    Fetches all vehicles (optionally filtered by tier) from the WoT encyclopedia.
    Returns (tag_to_name, tank_id_to_name).
    """
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])
    tag_to_name: dict[str, str] = {}
    tank_id_to_name: dict[int, str] = {}
    page = 1
    while True:
        enc = {
            "application_id": app_id,
            "fields": "tag,name,tank_id",
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
                tag_to_name[info["tag"]] = info["name"]
                if "tank_id" in info:
                    tank_id_to_name[info["tank_id"]] = info["name"]
        meta = data.get("meta", {})
        total_pages = meta.get("page_total", 1)
        if progress_cb:
            progress_cb(f"Tankopedia: page {page}/{total_pages} ({len(tag_to_name)} tanks)")
        if page >= total_pages:
            break
        page += 1
    return tag_to_name, tank_id_to_name


def resolve_vehicle_name(vehicle_type: str, tag_to_name: dict[str, str]) -> str | None:
    tag = vehicle_type.split(":", 1)[-1]
    return tag_to_name.get(tag)
