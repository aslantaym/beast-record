import os
import json
import csv
import requests
from datetime import datetime

API_KEY = os.getenv('YOUTUBE_API_KEY')
if not API_KEY:
    raise ValueError("Missing YOUTUBE_API_KEY environment variable")

CHANNEL_ID = "UCX6OQ3DkcsbYNE6H8uQQuVA"
PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"   # MrBeast uploads playlist

STATE_FILE = "state.json"
CSV_FILE = "data/mrbeast_views.csv"

def get_latest_video():
    url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&maxResults=1&playlistId={PLAYLIST_ID}&key={API_KEY}"
    resp = requests.get(url, timeout=15)
    data = resp.json()
    if data.get("items"):
        item = data["items"][0]
        return item["contentDetails"]["videoId"], item["snippet"]["title"]
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
video_id, title = get_latest_video()

if not video_id:
    print("Failed to fetch latest video")
    exit(1)

# Detect new video
if video_id != state.get("current_video_id"):
    print(f"🎉 New video detected: {title}")
    state = {"current_video_id": video_id, "title": title}
    save_state(state)

views = get_view_count(video_id)
if views is None:
    print("Failed to get view count")
    exit(1)

timestamp = datetime.utcnow().isoformat() + "Z"

# Append row
row = [timestamp, video_id, title, views]
file_exists = os.path.exists(CSV_FILE)

with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    if not file_exists:
        writer.writerow(["timestamp", "video_id", "title", "views"])
    writer.writerow(row)

print(f"✅ Logged {views:,} views for '{title[:80]}...' at {timestamp}")
