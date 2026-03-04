import os
import json
import requests
import re
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from datetime import datetime, timezone
import traceback

API_KEY = os.getenv('YOUTUBE_API_KEY')
if not API_KEY:
    raise ValueError("Missing YOUTUBE_API_KEY")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"
VIDEOS_DIR = "videos"
STATE_FILE = "state.json"

def sanitize_filename(title):
    clean = re.sub(r'[<>:\"/\\|?*]', '', title)
    clean = re.sub(r'[\s\-.,;:!?]+', '_', clean)
    clean = clean.strip('_')
    if len(clean) > 80:
        clean = clean[:77] + '...'
    return clean

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

def get_video_file(video_id, title):
    clean = sanitize_filename(title)
    return f"{VIDEOS_DIR}/{clean}_{video_id[:8]}.csv"

def get_graph_file(video_id, title):
    clean = sanitize_filename(title)
    return f"{VIDEOS_DIR}/{clean}_{video_id[:8]}_graph.png"

def get_vph_graph_file(video_id, title):
    clean = sanitize_filename(title)
    return f"{VIDEOS_DIR}/{clean}_{video_id[:8]}_vph_graph.png"

os.makedirs(VIDEOS_DIR, exist_ok=True)

state = load_state()
video_id, title = get_latest_longform_video()

if not video_id:
    if state.get("current_video_id"):
        print("⚠️ Using previous video")
        video_id = state["current_video_id"]
        title = state.get("current_title", "MrBeast Video")
    else:
        print("❌ No video found")
        exit(1)

video_file = get_video_file(video_id, title)
graph_file = get_graph_file(video_id, title)
vph_graph_file = get_vph_graph_file(video_id, title)

views = get_view_count(video_id)
if views is None:
    print("Failed to get views")
    exit(1)

timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

# ====================== SAVE DATA ======================
if video_id != state.get("current_video_id") or not os.path.exists(video_file):
    print(f"🎉 NEW LONG-FORM VIDEO: {title}")
    state = {"current_video_id": video_id, "current_title": title}
    save_state(state)
    
    df = pd.DataFrame([[timestamp, views, 0.0]], columns=["timestamp", "views", "vph"])
    df.to_csv(video_file, index=False)
    print(f"✅ First row written: {views:,} views | VPH=0.0")
else:
    df = pd.read_csv(video_file)
    prev_timestamp = pd.to_datetime(df.iloc[-1]['timestamp'])
    prev_views = int(df.iloc[-1]['views'])
    time_diff_hours = (pd.to_datetime(timestamp) - prev_timestamp).total_seconds() / 3600.0
    vph = (views - prev_views) / time_diff_hours if time_diff_hours > 0.001 else 0.0
    
    new_row = pd.DataFrame([[timestamp, views, round(vph, 1)]], columns=["timestamp", "views", "vph"])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(video_file, index=False)
    print(f"✅ Logged {views:,} views | VPH: {vph:,.1f}")

print(f"📊 CSV ready with {len(df)} rows")

# ====================== FORCE GRAPH UPDATE ======================
last_updated = f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\nCurrent views: {views:,}"

# Delete old graphs first (this is the key to force update)
for f in [graph_file, vph_graph_file]:
    if os.path.exists(f):
        os.remove(f)

# Views graph
df['timestamp'] = pd.to_datetime(df['timestamp'])
plt.figure(figsize=(12, 7))
plt.plot(df['timestamp'], df['views'], marker='o', linewidth=3, markersize=6, color='#FF0000')
plt.title(f"MrBeast — {title}\nView Growth Over Time", fontsize=16, pad=20)
plt.xlabel("Date & Time (UTC)")
plt.ylabel("Views")
plt.grid(True, alpha=0.4)
plt.xticks(rotation=45)
plt.text(0.02, 0.98, last_updated, transform=plt.gca().transAxes, fontsize=11, 
         verticalalignment='top', bbox=dict(boxstyle="round", facecolor="white", alpha=0.9))

def format_views(x, pos):
    if x >= 1_000_000: return f'{x/1_000_000:.1f}M'
    elif x >= 1_000: return f'{x/1_000:.0f}K'
    return f'{x:,.0f}'
plt.gca().yaxis.set_major_formatter(FuncFormatter(format_views))

plt.tight_layout()
plt.savefig(graph_file, dpi=250, bbox_inches='tight')
plt.close()
print(f"✅ Views graph UPDATED → {graph_file}")

# VPH graph
plt.figure(figsize=(12, 7))
plt.plot(df['timestamp'], df['vph'], marker='o', linewidth=3, markersize=6, color='#00AA00')
plt.title(f"MrBeast — {title}\nViews Per Hour (Velocity)", fontsize=16, pad=20)
plt.xlabel("Date & Time (UTC)")
plt.ylabel("Views Per Hour")
plt.grid(True, alpha=0.4)
plt.xticks(rotation=45)
plt.text(0.02, 0.98, last_updated, transform=plt.gca().transAxes, fontsize=11, 
         verticalalignment='top', bbox=dict(boxstyle="round", facecolor="white", alpha=0.9))

def format_vph(x, pos):
    if x >= 1_000_000: return f'{x/1_000_000:.1f}M/h'
    elif x >= 1_000: return f'{x/1_000:.0f}K/h'
    return f'{x:,.0f}/h'
plt.gca().yaxis.set_major_formatter(FuncFormatter(format_vph))

plt.tight_layout()
plt.savefig(vph_graph_file, dpi=250, bbox_inches='tight')
plt.close()
print(f"✅ VPH graph UPDATED → {vph_graph_file}")
