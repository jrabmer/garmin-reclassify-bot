#!/usr/bin/env python3
"""
Reclassify a Garmin Connect custom activity as another activity type
(e.g. relabel your Forerunner 165's custom activity as "Football").

Uses the unofficial `garminconnect` library (cyberjunky/python-garminconnect),
which logs into the same web session Garmin Connect's website uses. There is
no real-time webhook available to hobbyist developers, so this runs on a
daily schedule and looks back over the last N hours for matching activities.

Usage:
    python reclassify.py --login-only     # one-time interactive login, saves session tokens
    python reclassify.py --list-types      # print all valid activity type keys/ids
    python reclassify.py                   # normal run: find + reclassify matches

Environment variables:
    GARMIN_EMAIL            Garmin Connect account email (required)
    GARMIN_PASSWORD         Garmin Connect account password (required)
    GARMIN_TOKEN_DIR        Where session tokens are cached (default: /data/.garminconnect)
    SOURCE_MATCH_NAME       Case-insensitive substring to match in activityName (default: none)
    SOURCE_TYPE_KEY         Match on the activity's current typeKey instead/also (e.g. "other")
    TARGET_TYPE_KEY         typeKey to set, found via --list-types (required for normal run)
    LOOKBACK_HOURS          How far back to scan for new activities (default: 26)
    DRY_RUN                 If "1", log what would change but don't write anything
"""

import os
import sys
import logging
from datetime import datetime, timedelta, timezone

from garminconnect import Garmin, GarminConnectAuthenticationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reclassify")

TOKEN_DIR = os.environ.get(
    "GARMIN_TOKEN_DIR", os.path.expanduser("~/.garmin-reclassify/tokens")
)
ACTIVITY_TYPES_PATH = "/activity-service/activity/activityTypes"


def login() -> Garmin:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        sys.exit("GARMIN_EMAIL and GARMIN_PASSWORD must be set")

    client = Garmin(email=email, password=password)
    try:
        client.login(TOKEN_DIR)
    except FileNotFoundError:
        # No cached session yet — fall back to a fresh credential login.
        # If MFA is enabled on the account, this will fail headlessly;
        # run --login-only interactively first to seed the token cache.
        client.login()
        os.makedirs(TOKEN_DIR, exist_ok=True)
        client.garth.dump(TOKEN_DIR)
    except GarminConnectAuthenticationError as e:
        sys.exit(f"Login failed: {e}")
    return client


def list_activity_types(client: Garmin) -> None:
    types = client.connectapi(ACTIVITY_TYPES_PATH)
    for t in sorted(types, key=lambda x: x.get("typeKey", "")):
        print(f"{t.get('typeId'):>4}  {t.get('typeKey'):<30}  parent={t.get('parentTypeId')}")


def find_target_type(client: Garmin, target_key: str) -> dict:
    types = client.connectapi(ACTIVITY_TYPES_PATH)
    for t in types:
        if t.get("typeKey") == target_key:
            return t
    sys.exit(
        f"typeKey '{target_key}' not found. Run --list-types to see valid options."
    )


def find_matching_activities(client: Garmin) -> list[dict]:
    lookback_hours = int(os.environ.get("LOOKBACK_HOURS", "26"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    name_match = os.environ.get("SOURCE_MATCH_NAME", "").strip().lower()
    type_match = os.environ.get("SOURCE_TYPE_KEY", "").strip().lower()

    activities = client.get_activities(0, 20)  # most recent 20 is plenty for a daily run
    matches = []
    for a in activities:
        start_str = a.get("startTimeGMT")  # e.g. "2026-08-25 06:12:00"
        if not start_str:
            continue
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        if start_dt < cutoff:
            continue

        current_key = (a.get("activityType") or {}).get("typeKey", "").lower()
        name = (a.get("activityName") or "").lower()

        if name_match and name_match not in name:
            continue
        if type_match and current_key != type_match:
            continue
        if not name_match and not type_match:
            continue  # require at least one filter, to avoid relabeling everything

        matches.append(a)
    return matches


def reclassify(client: Garmin, activity: dict, target_type: dict, dry_run: bool) -> None:
    activity_id = activity["activityId"]
    old_key = (activity.get("activityType") or {}).get("typeKey")
    label = activity.get("activityName")

    if dry_run:
        log.info(
            "[DRY RUN] Would reclassify activity %s (%r): %s -> %s",
            activity_id, label, old_key, target_type["typeKey"],
        )
        return

    payload = {
        "activityId": activity_id,
        "activityTypeDTO": {
            "typeId": target_type["typeId"],
            "typeKey": target_type["typeKey"],
            "parentTypeId": target_type.get("parentTypeId"),
        },
    }
    # Mirrors the internal pattern the library itself uses for writes
    # (see set_activity_description in garminconnect/__init__.py):
    # self.client is the underlying garth Client, whose .put() takes the
    # endpoint type, path, and json body directly.
    client.client.put(
        "connectapi", f"/activity-service/activity/{activity_id}", json=payload, api=True
    )
    log.info("Reclassified activity %s (%r): %s -> %s", activity_id, label, old_key, target_type["typeKey"])


def main() -> None:
    client = login()

    if "--login-only" in sys.argv:
        log.info("Login successful, session cached at %s", TOKEN_DIR)
        return

    if "--list-types" in sys.argv:
        list_activity_types(client)
        return

    target_key = os.environ.get("TARGET_TYPE_KEY")
    if not target_key:
        sys.exit("TARGET_TYPE_KEY must be set. Run --list-types to find the right value.")
    target_type = find_target_type(client, target_key)

    dry_run = os.environ.get("DRY_RUN") == "1"
    matches = find_matching_activities(client)

    if not matches:
        log.info("No matching activities in the last %s hours.", os.environ.get("LOOKBACK_HOURS", "26"))
        return

    for activity in matches:
        reclassify(client, activity, target_type, dry_run)


if __name__ == "__main__":
    main()
