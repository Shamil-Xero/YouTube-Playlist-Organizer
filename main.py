import argparse
import re
import time

import requests
import yaml

from auth import get_youtube_client
from categorizer import classify
from lm_studio_client import LMStudioClient
from state import StateStore
from youtube_api import YouTubeClient


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def parse_iso8601_duration(duration: str) -> int:
    """Convert an ISO 8601 duration (e.g. 'PT1M30S') to total seconds."""
    if not duration:
        return 0
    match = re.match(
        r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        duration,
    )
    if not match:
        return 0
    h = int(match.group("hours") or 0)
    m = int(match.group("minutes") or 0)
    s = int(match.group("seconds") or 0)
    return h * 3600 + m * 60 + s


def format_seconds(seconds: int) -> str:
    """Format total seconds to a human-readable duration (e.g. '3:45' or '45s')."""
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(description="Auto-sort a YouTube playlist using a local LLM.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Classify only, don't touch playlists")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N videos")
    args = parser.parse_args()

    cfg = load_config(args.config)
    yt_cfg = cfg["youtube"]
    lmstudio_cfg = cfg["lmstudio"]
    categories = cfg["categories"]
    review_cfg = cfg.get("review", {})

    llm = LMStudioClient(
        lmstudio_cfg["host"],
        lmstudio_cfg.get("model", ""),
        lmstudio_cfg.get("timeout_seconds", 60),
        lmstudio_cfg.get("api_key", "lm-studio"),
    )
    try:
        print(f"Using LM Studio model: {llm.resolve_model()}")
    except requests.exceptions.ConnectionError:
        raise SystemExit(
            f"Could not reach LM Studio's server at {lmstudio_cfg['host']}. "
            "Start it from the Developer tab (Start Server) or `lms server start`, "
            "then re-run this script."
        )
    except RuntimeError as e:
        raise SystemExit(str(e))

    print("Authenticating with YouTube...")
    service = get_youtube_client(yt_cfg["client_secret_file"], yt_cfg["token_file"])
    yt = YouTubeClient(service)
    state = StateStore("processed.json")

    print(f"Fetching source playlist {yt_cfg['source_playlist_id']}...")
    items = yt.get_playlist_items(yt_cfg["source_playlist_id"])
    if args.limit:
        items = items[: args.limit]
    print(f"Found {len(items)} videos.")

    video_ids = [it["video_id"] for it in items]
    details = yt.get_video_details(video_ids)

    # --- Remove private/deleted videos ---
    DEAD_TITLES = {"private video", "deleted video"}
    removed_dead = 0
    alive_items = []
    for it in items:
        vid = it["video_id"]
        is_dead = (vid not in details) or it["title"].strip().lower() in DEAD_TITLES
        if is_dead:
            print(f"  [remove] Private/deleted: {it['title']!r}")
            if not args.dry_run:
                try:
                    yt.remove_playlist_item(it["playlist_item_id"])
                except Exception as e:
                    print(f"    Could not remove: {e}")
            state.mark_done(vid, "removed", note="private/deleted")
            removed_dead += 1
        else:
            alive_items.append(it)
    if removed_dead:
        print(f"  Cleaned up {removed_dead} private/deleted video(s).")
    items = alive_items

    playlist_id_cache = {c["name"]: (c.get("playlist_id") or None) for c in categories}

    # Shorts handling
    shorts_cfg = cfg.get("shorts", {})
    shorts_enabled = shorts_cfg.get("enabled", False)
    shorts_max_seconds = shorts_cfg.get("max_duration_seconds", 60)
    shorts_playlist_id = shorts_cfg.get("playlist_id") or None
    shorts_moved = 0

    to_review = []
    moved = 0
    results = []  # (title, category) for summary table

    delay = review_cfg.get("batch_delay_seconds", 0.5)
    min_confidence = review_cfg.get("min_confidence", "medium")

    # --- Pre-calculate pending count ---
    pending_items = [it for it in items if not state.is_done(it["video_id"])]
    total_pending = len(pending_items)

    if total_pending > 0:
        print(f"\nProcessing {total_pending} new video(s)...")
    else:
        print("\nNo new videos to process (all have already been categorized).")

    current_index = 0
    for it in items:
        vid = it["video_id"]
        if state.is_done(vid):
            continue

        current_index += 1
        vdetails = details.get(vid)
        if not vdetails:
            print(f"[{current_index}/{total_pending}] [skip] Could not fetch details for {vid} ({it['title']})")
            continue

        # Extract metadata
        channel = vdetails.get("channel", "Unknown Channel")
        duration_raw = vdetails.get("duration", "")
        duration_sec = parse_iso8601_duration(duration_raw)
        duration_str = format_seconds(duration_sec) if duration_sec > 0 else "Unknown duration"

        print(f"\n[{current_index}/{total_pending}] Processing: {it['title']!r}")
        print(f"  - Channel: {channel} | Duration: {duration_str}")

        # --- Shorts detection (by duration, before LLM) ---
        if shorts_enabled:
            if 0 < duration_sec <= shorts_max_seconds:
                print(f"  - Action: Detected YouTube Short ({duration_sec}s).")
                if not args.dry_run:
                    if not shorts_playlist_id:
                        shorts_playlist_id = yt.get_or_create_playlist(
                            "Shorts", "YouTube Shorts (auto-sorted by duration)"
                        )
                        print(f"    (created/found Shorts playlist: {shorts_playlist_id})")
                    yt.add_video_to_playlist(shorts_playlist_id, vid)
                    if yt_cfg.get("remove_from_source", True):
                        yt.remove_playlist_item(it["playlist_item_id"])
                    state.mark_done(vid, "Shorts", note=f"{duration_sec}s")
                    print(f"  - Result: Moved to 'Shorts' playlist.")
                else:
                    print(f"  - Result: [Dry-run] Would move to 'Shorts' playlist.")

                results.append((it["title"], "Shorts"))
                shorts_moved += 1
                time.sleep(delay)
                continue

        category, confidence, reason, suggested = classify(vdetails, categories, llm, min_confidence)

        if category is None:
            suggestion_msg = f", Suggestion: \"{suggested}\"" if suggested else ""
            print(f"  - LLM Classification: Uncertain (Confidence: {confidence})")
            print(f"    Reason: {reason}{suggestion_msg}")
            print(f"  - Action: Kept in source playlist, queued for manual review.")
            to_review.append({**it, "suggested_category": suggested})
            results.append((it["title"], "[needs review]"))
            time.sleep(delay)
            continue

        print(f"  - LLM Classification: '{category}' (Confidence: {confidence})")
        print(f"    Reason: {reason}")

        if args.dry_run:
            print(f"  - Action: [Dry-run] Would move to '{category}' playlist.")
            results.append((it["title"], category))
            time.sleep(delay)
            continue

        dest_id = playlist_id_cache.get(category)
        if not dest_id:
            cat_cfg = next(c for c in categories if c["name"] == category)
            dest_id = yt.get_or_create_playlist(category, cat_cfg.get("description", ""))
            playlist_id_cache[category] = dest_id
            print(f"    (created/found playlist for '{category}': {dest_id})")

        yt.add_video_to_playlist(dest_id, vid)
        if yt_cfg.get("remove_from_source", True):
            yt.remove_playlist_item(it["playlist_item_id"])
        print(f"  - Action: Moved to '{category}' playlist.")

        state.mark_done(vid, category)
        results.append((it["title"], category))
        moved += 1
        time.sleep(delay)

    # --- Summary table ---
    if results:
        print("\n" + "=" * 80)
        print(f" {'Video Title':<55} {'Category':<22}")
        print("-" * 80)
        for title, cat in results:
            truncated = (title[:52] + "...") if len(title) > 55 else title
            print(f" {truncated:<55} {cat:<22}")
        print("=" * 80)

    if shorts_enabled:
        print(f"Shorts routed: {shorts_moved}")
    print(f"Done. Moved {moved} videos automatically.")

    if to_review and not args.dry_run:
        review_uncategorized(to_review, categories, yt, playlist_id_cache, yt_cfg, state)
    elif to_review:
        print(f"{len(to_review)} video(s) need manual review (skipped in dry-run).")


def review_uncategorized(to_review, categories, yt, playlist_id_cache, yt_cfg, state):
    print(f"\n{len(to_review)} video(s) couldn't be confidently categorized. Review them now? [y/N] ", end="")
    if input().strip().lower() != "y":
        print("Skipping review. Re-run the script later to review these "
              "(they weren't marked as processed, so they'll show up again).")
        return

    names = [c["name"] for c in categories]
    for it in to_review:
        suggested = it.get("suggested_category", "")
        print(f"\n{it['title']}")
        print(f"https://www.youtube.com/watch?v={it['video_id']}")
        for i, name in enumerate(names, 1):
            print(f"  {i}. {name}")
        if suggested:
            print(f"  s. ✨ Create new: \"{suggested}\" (LLM suggestion)")
        print(f"  n. Enter a custom new category name")
        print(f"  0. Skip (leave in source playlist)")
        choice = input("Choose: ").strip()

        if choice == "0" or not choice:
            continue

        category = None

        if choice.lower() == "s" and suggested:
            category = suggested
        elif choice.lower() == "n":
            custom = input("  Enter new category name: ").strip()
            if not custom:
                print("  Empty name, skipping.")
                continue
            category = custom
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                category = names[idx]
            else:
                print("  Invalid choice, skipping.")
                continue
        else:
            print("  Invalid choice, skipping.")
            continue

        dest_id = playlist_id_cache.get(category)
        if not dest_id:
            dest_id = yt.get_or_create_playlist(category)
            playlist_id_cache[category] = dest_id
            print(f"    (created/found playlist for '{category}': {dest_id})")

        yt.add_video_to_playlist(dest_id, it["video_id"])
        if yt_cfg.get("remove_from_source", True):
            yt.remove_playlist_item(it["playlist_item_id"])
        state.mark_done(it["video_id"], category, note="manual review")
        print(f"  -> moved to {category}")


if __name__ == "__main__":
    main()
