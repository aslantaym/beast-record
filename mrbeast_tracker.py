import os
import json
import csv
import requests
import re
from datetime import datetime
import pandas as pd
import matplotlib
matplotlib.use('Agg')          # ← This fixes the #1 GitHub Actions crash
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import traceback               # For clear error messages if anything else fails

API_KEY = os.getenv('YOUTUBE_API_KEY')
if not API_KEY:
    raise ValueError("Missing YOUTUBE_API_KEY")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"
VIDEOS_DIR = "videos"
STATE_FILE = "state.json"

def parse_iso_duration(duration):
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
    url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&maxResults=20&playlistId={PLAYLIST_ID}&key={API_KEY}"
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"Playlist fetch error: {e}")
        return None, None

    if not data.get("items"):
        return None, None

    video_ids = [item["contentDetails"]["videoId"] for item in data["items"]]
    ids_str = ",".join(video_ids)

    detail_url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,snippet&id={ids_str}&key={API_KEY}"
    try:
        detail_resp = requests.get(detail_url, timeout=15)
        detail_data = detail_resp.json()
    except Exception as e:
        print(f"Details fetch error: {e}")
        return None, None

    video_map = {}
    for item in detail_data.get("items", []):
        vid = item["id"]
        dur_str = item["contentDetails"].get("duration")
        title = item["snippet"]["title"]
        secs = parse_iso_duration(dur_str)
        video_map[vid] = (secs, title)

    # Find newest long-form (> 3 minutes)
    for item in data["items"]:
        vid = item["contentDetails"]["videoId"]
        if vid in video_map:
            secs, title = video_map[vid]
            if secs > 180:
                print(f"✅ Using long-form video: {title}")
                return vid, title
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
    return {"current_video_id": None, "current_title": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_video_file(video_id):
    return f"{VIDEOS_DIR}/{video_id}.csv"

def get_graph_file(video_id):
    return f"{VIDEOS_DIR}/{video_id}_graph.png"

os.makedirs(VIDEOS_DIR, exist_ok=True)

state = load_state()
video_id, title = get_latest_longform_video()

# Fallback: if we can't find a long-form right now, keep tracking the previous one
if not video_id:
    if state.get("current_video_id"):
        print("⚠️ Could not fetch newest long-form video right now → continuing with previous video")
        video_id = state["current_video_id"]
        title = state.get("current_title", "MrBeast Video")
    else:
        print("❌ No long-form video found and no previous one saved")
        exit(1)

video_file = get_video_file(video_id)

# New video detected
if video_id != state.get("current_video_id"):
    print(f"🎉 NEW LONG-FORM VIDEO DETECTED: {title}")
    state = {"current_video_id": video_id, "current_title": title}
    save_state(state)
    
    # Fresh CSV for this video
    with open(video_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "views"])

# Log views
views = get_view_count(video_id)
if views is None:
    print("Failed to get view count")
    exit(1)

timestamp = datetime.utcnow().isoformat() + "Z"
with open(video_file, "a", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([timestamp, views])

print(f"✅ Logged {views:,} views → {video_file}")

# Generate graph (wrapped so it never crashes the whole script)
try:
    df = pd.read_csv(video_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    plt.figure(figsize=(12, 7))
    plt.plot(df['timestamp'], df['views'], marker='o', linewidth=2.5, markersize=5, color='#FF0000')

    plt.title(f"MrBeast — {title}\nView Growth Over Time", fontsize=16, pad=20)
    plt.xlabel("Date & Time (UTC)")
    plt.ylabel("Views")
    plt.grid(True, alpha=0.4)
    plt.xticks(rotation=45)

    def format_views(x, pos):
        if x >= 1_000_000:
            return f'{x/1_000_000:.1f}M'
        elif x >= 1_000:
            return f'{x/1_000:.0f}K'
        return f'{x:,.0f}'
    plt.gca().yaxis.set_major_formatter(FuncFormatter(format_views))

    plt.tight_layout()
    plt.savefig(get_graph_file(video_id), dpi=250, bbox_inches='tight')
    plt.close()
    print(f"📈 Graph updated → {get_graph_file(video_id)}")
except Exception as e:
    print("⚠️ Graph generation failed (but views were saved):")
    print(traceback.format_exc())
