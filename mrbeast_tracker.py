import os
import json
import requests
import re
import unicodedata
from datetime import datetime, timezone

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import traceback

API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    raise ValueError("Missing YOUTUBE_API_KEY")

PLAYLIST_ID = "UUX6OQ3DkcsbYNE6H8uQQuVA"
VIDEOS_DIR = "videos"
STATE_FILE = "state.json"


# -------------------- helpers --------------------
def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_filename(title: str) -> str:
    """
    Make filenames stable & portable:
    - remove emojis / non-ascii
    - keep only A-Z a-z 0-9 and underscores
    """
    if not title:
        return "MrBeast_Video"

    # strip emojis / accents
    title = unicodedata.normalize("NFKD", title)
    title = title.encode("ascii", "ignore").decode("ascii")

    # keep safe chars
    clean = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")
    if not clean:
        clean = "MrBeast_Video"

    return clean[:80]


def parse_iso_duration(duration):
    if not duration:
        return 0
    match = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"current_video_id": None, "current_title": ""}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("state.json not a dict")
        return {
            "current_video_id": data.get("current_video_id"),
            "current_title": data.get("current_title", ""),
        }
    except Exception as e:
        print(f"⚠️ Could not read state.json (will reset). Reason: {e}")
        return {"current_video_id": None, "current_title": ""}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def get_latest_longform_video():
    url = (
        "https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet,contentDetails&maxResults=20&playlistId={PLAYLIST_ID}&key={API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=20)
        data = resp.json()
    except Exception as e:
        print(f"Playlist fetch error: {e}")
        return None, None

    if not data.get("items"):
        return None, None

    video_ids = [item["contentDetails"]["videoId"] for item in data["items"]]
    ids_str = ",".join(video_ids)

    detail_url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=contentDetails,snippet&id={ids_str}&key={API_KEY}"
    )
    try:
        detail_resp = requests.get(detail_url, timeout=20)
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

    # Choose first upload that is >3 minutes
    for item in data["items"]:
        vid = item["contentDetails"]["videoId"]
        if vid in video_map:
            secs, title = video_map[vid]
            if secs > 180:
                print(f"✅ Using long-form video: {title}")
                return vid, title

    return None, None


def get_view_count(video_id):
    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=statistics&id={video_id}&key={API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=20)
        data = resp.json()
        if data.get("items"):
            return int(data["items"][0]["statistics"]["viewCount"])
    except Exception:
        pass
    return None


def get_video_file(video_id, title):
    clean = sanitize_filename(title)
    return f"{VIDEOS_DIR}/{clean}_{video_id[:8]}.csv"


def get_graph_file(video_id, title):
    clean = sanitize_filename(title)
    return f"{VIDEOS_DIR}/{clean}_{video_id[:8]}_graph.png"


def get_vph_graph_file(video_id, title):
    clean = sanitize_filename(title)
    return f"{VIDEOS_DIR}/{clean}_{video_id[:8]}_vph_graph.png"


def load_video_df(path: str) -> pd.DataFrame:
    cols = ["timestamp", "views", "vph"]
    if (not os.path.exists(path)) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=cols)

    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=cols)

    # enforce columns
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[cols]
    return df


def atomic_write_csv(path: str, df: pd.DataFrame):
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


def compute_vph(df: pd.DataFrame, curr_ts: str, curr_views: int) -> float:
    if df.empty:
        return 0.0

    prev = df.iloc[-1]
    prev_ts = pd.to_datetime(prev["timestamp"], utc=True, errors="coerce")
    prev_views = pd.to_numeric(prev["views"], errors="coerce")
    curr_ts_dt = pd.to_datetime(curr_ts, utc=True, errors="coerce")

    if pd.isna(prev_ts) or pd.isna(prev_views) or pd.isna(curr_ts_dt):
        return 0.0

    dt_hours = (curr_ts_dt - prev_ts).total_seconds() / 3600.0
    if dt_hours <= 0.0005:
        return 0.0

    return float(curr_views - float(prev_views)) / dt_hours


def atomic_savefig(final_path: str):
    tmp = final_path + ".tmp.png"
    plt.savefig(tmp, dpi=250, bbox_inches="tight")
    plt.close()
    os.replace(tmp, final_path)


# -------------------- main --------------------
os.makedirs(VIDEOS_DIR, exist_ok=True)

state = load_state()
video_id, title = get_latest_longform_video()

if not video_id:
    if state.get("current_video_id"):
        print("⚠️ Using previous video from state.json")
        video_id = state["current_video_id"]
        title = state.get("current_title", "MrBeast Video")
    else:
        print("❌ No video found")
        raise SystemExit(1)

video_file = get_video_file(video_id, title)
graph_file = get_graph_file(video_id, title)
vph_graph_file = get_vph_graph_file(video_id, title)

views = get_view_count(video_id)
if views is None:
    print("❌ Failed to get views (API error). Keeping previous CSV/graphs.")
    raise SystemExit(1)

timestamp = utc_now_iso_z()

# Handle state switch
if video_id != state.get("current_video_id"):
    print(f"🎉 NEW LONG-FORM VIDEO: {title}")
    state = {"current_video_id": video_id, "current_title": title}
    save_state(state)

# Load/append safely (always results in at least 1 row now)
df = load_video_df(video_file)
vph = compute_vph(df, timestamp, views)

new_row = pd.DataFrame([{
    "timestamp": timestamp,
    "views": int(views),
    "vph": round(float(vph), 1),
}])

df = pd.concat([df, new_row], ignore_index=True)
atomic_write_csv(video_file, df)

print(f"✅ Logged {views:,} views | VPH: {vph:,.1f} | rows={len(df)}")

# -------------------- graphs --------------------
last_updated = f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

# Prepare df for plotting
df_plot = df.copy()
df_plot["timestamp"] = pd.to_datetime(df_plot["timestamp"], utc=True, errors="coerce")
df_plot["views"] = pd.to_numeric(df_plot["views"], errors="coerce")
df_plot["vph"] = pd.to_numeric(df_plot["vph"], errors="coerce")
df_plot = df_plot.dropna(subset=["timestamp"])
df_plot = df_plot.sort_values("timestamp")

def format_views(x, pos):
    if x >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"{x/1_000:.0f}K"
    return f"{x:,.0f}"

def format_vph(x, pos):
    if x >= 1_000_000:
        return f"{x/1_000_000:.1f}M/h"
    if x >= 1_000:
        return f"{x/1_000:.0f}K/h"
    return f"{x:,.0f}/h"

# Views graph
try:
    plt.figure(figsize=(12, 7))

    if len(df_plot) == 0:
        plt.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=18)
        plt.axis("off")
    else:
        plt.plot(df_plot["timestamp"], df_plot["views"], marker="o", linewidth=3, markersize=6)
        plt.title(f"MrBeast — {title}\nView Growth Over Time", fontsize=16, pad=20)
        plt.xlabel("Date & Time (UTC)")
        plt.ylabel("Views")
        plt.grid(True, alpha=0.4)
        plt.xticks(rotation=45)
        plt.gca().yaxis.set_major_formatter(FuncFormatter(format_views))

        # if only one point, ensure marker is visible
        if len(df_plot) == 1:
            y = float(df_plot["views"].iloc[0])
            plt.ylim(y * 0.99, y * 1.01 + 1)

        plt.text(
            0.02, 0.98, last_updated,
            transform=plt.gca().transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

    plt.tight_layout()
    atomic_savefig(graph_file)
    print(f"✅ Views graph UPDATED → {graph_file}")
except Exception:
    print("❌ Views graph failed:")
    print(traceback.format_exc())

# VPH graph
try:
    plt.figure(figsize=(12, 7))

    if len(df_plot) == 0:
        plt.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=18)
        plt.axis("off")
    else:
        plt.plot(df_plot["timestamp"], df_plot["vph"], marker="o", linewidth=3, markersize=6)
        plt.title(f"MrBeast — {title}\nViews Per Hour (Velocity)", fontsize=16, pad=20)
        plt.xlabel("Date & Time (UTC)")
        plt.ylabel("Views Per Hour")
        plt.grid(True, alpha=0.4)
        plt.xticks(rotation=45)
        plt.gca().yaxis.set_major_formatter(FuncFormatter(format_vph))

        if len(df_plot) == 1:
            y = float(df_plot["vph"].iloc[0])
            plt.ylim(y - 1, y + 1)

        plt.text(
            0.02, 0.98, last_updated,
            transform=plt.gca().transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

    plt.tight_layout()
    atomic_savefig(vph_graph_file)
    print(f"✅ VPH graph UPDATED → {vph_graph_file}")
except Exception:
    print("❌ VPH graph failed:")
    print(traceback.format_exc())
