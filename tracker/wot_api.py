"""
WoT API helpers — clan membership and account tank lookups.
"""

import urllib.request
import urllib.parse
import json
import sys

from .constants import REALM_URLS


def fetch_clan_member_ids(app_id: str, realm: str, clan_tag: str) -> list[int]:
    """Returns list of account_ids for all members of the given clan tag."""
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])

    # Search for clan
    params = urllib.parse.urlencode({
        "application_id": app_id,
        "search": clan_tag,
        "fields": "clan_id,tag",
        "limit": 10,
    })
    url = f"{base_url}/wot/clans/list/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[!] Clan search failed: {e}", file=sys.stderr)
        return []

    clan_id = None
    for clan in data.get("data", []):
        if clan.get("tag", "").upper() == clan_tag.upper():
            clan_id = clan["clan_id"]
            break
    if not clan_id:
        return []

    # Fetch clan members
    params = urllib.parse.urlencode({
        "application_id": app_id,
        "clan_id": clan_id,
        "fields": "members",
    })
    url = f"{base_url}/wot/clans/info/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[!] Clan info fetch failed: {e}", file=sys.stderr)
        return []

    clan_data = data.get("data", {}).get(str(clan_id), {})
    members = clan_data.get("members", [])
    return [m["account_id"] for m in members if "account_id" in m]


def fetch_tanks_for_accounts(
    app_id: str,
    realm: str,
    account_ids: list[int],
    tank_id_to_name: dict[int, str],
    tier: int,
    progress_cb=None,
) -> dict[int, list[str]]:
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])
    valid_ids = set(tank_id_to_name.keys())
    result: dict[int, list[str]] = {}

    batch_size = 100
    for i in range(0, len(account_ids), batch_size):
        batch = account_ids[i:i + batch_size]
        params = urllib.parse.urlencode({
            "application_id": app_id,
            "account_id": ",".join(str(a) for a in batch),
            "fields": "tank_id",
        })
        url = f"{base_url}/wot/account/tanks/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())

            if data.get("status") == "ok":
                for acc_id_str, tanks in data.get("data", {}).items():
                    acc_id = int(acc_id_str)
                    if not tanks:
                        continue
                    owned_names = [
                        tank_id_to_name[t["tank_id"]]
                        for t in tanks
                        if t.get("tank_id") in valid_ids
                    ]
                    if owned_names:
                        result[acc_id] = sorted(owned_names)

        except Exception as e:
            if progress_cb:
                progress_cb(f"Error fetching batch: {e}")

    return result


def fetch_account_names(app_id: str, realm: str, account_ids: list[int]) -> dict[int, str]:
    """Returns {account_id: nickname}."""
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])
    result: dict[int, str] = {}
    batch_size = 100
    for i in range(0, len(account_ids), batch_size):
        batch = account_ids[i:i + batch_size]
        params = urllib.parse.urlencode({
            "application_id": app_id,
            "account_id":     ",".join(str(a) for a in batch),
            "fields":         "nickname",
        })
        url = f"{base_url}/wot/account/info/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[!] Account names fetch failed: {e}", file=sys.stderr)
            continue
        for acc_id_str, info in data.get("data", {}).items():
            if info and "nickname" in info:
                result[int(acc_id_str)] = info["nickname"]
    return result
