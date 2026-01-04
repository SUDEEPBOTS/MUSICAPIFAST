import os
import time
import datetime
import subprocess
import requests
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from youtubesearchpython import VideosSearch

# ─────────────────────────────
# ENV CONFIG
# ─────────────────────────────
MONGO_URL = os.getenv("MONGO_DB_URI")
BOT_TOKEN = os.getenv("BOT_TOKEN")          # DM notify ke liye
ADMIN_CONTACT = "@Kaito_3_2"

CATBOX_UPLOAD = "https://catbox.moe/user/api.php"
COOKIES_PATH = "/app/cookies.txt"           # Docker root

# ─────────────────────────────
# APP
# ─────────────────────────────
app = FastAPI(title="Sudeep Music API ⚡ Video Auto")

mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["MusicAPI_DB1"]

videos_col = db["videos_cachet"]   # video cache
keys_col = db["api_users"]         # api keys (bot + api shared)

# Ultra-fast RAM cache
MEM_CACHE = {}

# ─────────────────────────────
# API KEY VERIFY
# ─────────────────────────────
async def verify_api_key(key: str):
    doc = await keys_col.find_one({"api_key": key, "active": True})
    if not doc:
        return False, "Invalid API key"

    now = int(time.time())

    # ⛔ Expired
    if now > doc["expires_at"]:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": doc["user_id"],
                    "text": (
                        "⚠️ Your API key has expired.\n\n"
                        f"Please contact {ADMIN_CONTACT} to renew."
                    )
                },
                timeout=10
            )
        except:
            pass

        return False, "API key expired"

    # 🔄 Daily reset
    today = str(datetime.date.today())
    if doc.get("last_reset") != today:
        await keys_col.update_one(
            {"api_key": key},
            {"$set": {"used_today": 0, "last_reset": today}}
        )
        doc["used_today"] = 0

    # 🚫 Limit
    if doc["used_today"] >= doc["daily_limit"]:
        return False, "Daily limit exceeded"

    # ➕ Count usage
    await keys_col.update_one(
        {"api_key": key},
        {"$inc": {"used_today": 1}}
    )

    return True, None

# ─────────────────────────────
# HELPERS
# ─────────────────────────────
def yt_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"

def extract_video_id(q: str):
    q = q.strip()
    if len(q) == 11 and " " not in q:
        return q
    if "v=" in q:
        return q.split("v=")[1].split("&")[0]
    if "youtu.be/" in q:
        return q.split("youtu.be/")[1].split("?")[0]
    return None

def search_youtube(query: str):
    try:
        s = VideosSearch(query, limit=1)
        r = s.result().get("result")
        if not r:
            return None, None
        return r[0]["id"], r[0]["title"]
    except:
        return None, None

def upload_catbox(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            CATBOX_UPLOAD,
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=180
        )
    if r.text.startswith("https://"):
        return r.text.strip()
    raise Exception("Catbox upload failed")

def auto_download_video(video_id: str) -> str:
    if not os.path.exists(COOKIES_PATH):
        raise Exception("cookies.txt missing")

    out = f"/tmp/{video_id}.mp4"

    cmd = [
        "python", "-m", "yt_dlp",
        "--cookies", COOKIES_PATH,
        "--js-runtimes", "node",
        "--no-playlist",
        "--geo-bypass",
        "--force-ipv4",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        yt_url(video_id),
        "-o", out
    ]

    subprocess.run(cmd, check=True, timeout=900)
    return out

# ─────────────────────────────
# MAIN VIDEO API
# ─────────────────────────────
@app.get("/getvideo")
async def get_video(query: str, key: str | None = None):

    # 🔐 API key required
    if not key:
        return {"status": 401, "error": "API key required"}

    ok, err = await verify_api_key(key)
    if not ok:
        return {"status": 403, "error": err}

    # 🔎 Extract or search
    video_id = extract_video_id(query)
    title = None

    if not video_id:
        video_id, title = search_youtube(query)
        if not video_id:
            return {
                "status": 404,
                "title": None,
                "link": None,
                "video_id": None
            }

    # ⚡ RAM cache
    if video_id in MEM_CACHE:
        return MEM_CACHE[video_id]

    # 💾 DB cache
    cached = await videos_col.find_one({"video_id": video_id})
    if cached:
        resp = {
            "status": 200,
            "title": cached["title"],
            "link": cached["catbox_link"],
            "video_id": video_id
        }
        MEM_CACHE[video_id] = resp
        return resp

    # ⬇️ Auto download → Catbox
    try:
        file_path = auto_download_video(video_id)
        catbox = upload_catbox(file_path)

        try:
            os.remove(file_path)
        except:
            pass

        await videos_col.update_one(
            {"video_id": video_id},
            {"$set": {
                "video_id": video_id,
                "title": title or video_id,
                "catbox_link": catbox
            }},
            upsert=True
        )

        resp = {
            "status": 200,
            "title": title or video_id,
            "link": catbox,
            "video_id": video_id
        }
        MEM_CACHE[video_id] = resp
        return resp

    except Exception as e:
        return {
            "status": 500,
            "title": None,
            "link": None,
            "video_id": video_id,
            "error": str(e)
        }

# ─────────────────────────────
# HEALTH / UPTIME
# ─────────────────────────────
@app.api_route("/", methods=["GET", "HEAD"])
async def home():
    return {"status": 200}
