import os
import json
import csv
import requests
import re
from datetime import datetime

API_KEY = os.getenv('YOUTUBE_API_KEY')
if not API_KEY:
    raise ValueError("Missing YOUTUBE_API_KEY environment variable")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"

STATE_FILE = "state.json"
CSV_FILE = "data/mrbeast_views.csv"

def parse_iso_duration(duration):
    """Convert PT10M5S → seconds"""
    if not duration:
        return 0
    hours = minutes = seconds = 0
    match = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds

def get_latest_longform_video():
    # Get last 10 uploads (newest first)
    url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&maxResults=10&playlistId={PLAYLIST_ID}&key={API_KEY}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching playlist: {e}")
        return None, None

    if not data.get("items"):
        return None, None

    video_ids = [item["contentDetails"]["videoId"] for item in data["items"]]

    # Batch get durations + titles
    ids_str = ",".join(video_ids)
    detail_url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,snippet&id={ids_str}&key={API_KEY}"
    try:
        detail_resp = requests.get(detail_url, timeout=15)
        detail_resp.raise_for_status()
        detail_data = detail_resp.json()
    except Exception as e:
        print(f"Error fetching details: {e}")
        return None, None

    # Map videoId → (duration_seconds, title)
    video_map = {}
    for item in detail_data.get("items", []):
        vid = item["id"]
        dur_str = item["contentDetails"].get("duration")
        title = item["snippet"]["title"]
        secs = parse_iso_duration(dur_str)
        video_map[vid] = (secs, title)

    # Pick the NEWEST long-form video (> 3 minutes = 180 seconds)
    for item in data["items"]:
        vid = item["contentDetails"]["videoId"]
        if vid in video_map:
            secs, title = video_map[vid]
            if secs > 180:   # ← This skips all Shorts
                print(f"✅ Long-form video found: {title} ({secs} seconds)")
                return vid, title

    print("⚠️ No long-form video found in recent uploads (all Shorts?)")
    return None, None

def get_view_count(video_id):
    url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={video_id}&key={API_KEY}"
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
        if data.get("items"):
            return int(data["items"][0]["statistics"]["viewCount"])
    except:
        pass
    return None

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"current_video_id": None, "title": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# Main logic
os.makedirs("data", exist_ok=True)

state = load_state()
video_id, title = get_latest_longform_video()

if not video_id:
    print("Failed to find a long-form video")
    exit(1)

# Detect new long-form video
if video_id != state.get("current_video_id"):
    print(f"🎉 New LONG-FORM video detected: {title}")
    state = {"current_video_id": video_id, "title": title}
    save_state(state)

views = get_view_count(video_id)
if views is None:
    print("Failed to get view count")
    exit(1)

timestamp = datetime.utcnow().isoformat() + "Z"

row = [timestamp, video_id, title, views]
file_exists = os.path.exists(CSV_FILE)

with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    if not file_exists:
        writer.writerow(["timestamp", "video_id", "title", "views"])
    writer.writerow(row)

print(f"✅ Logged {views:,} views for LONG-FORM video '{title[:80]}...' at {timestamp}")
