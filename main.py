import os
from fastapi import FastAPI, HTTPException
from pymongo import MongoClient
from youtubesearchpython import VideosSearch

app = FastAPI(title="Sudeep's Music API - Super Smart Mode")

MONGO_URL = os.getenv("MONGO_DB_URI")
client = MongoClient(MONGO_URL)
db = client["MusicAPI_DB"]
collection = db["songs_cache"]

@app.get("/get")
def get_music(query: str):
    # 1. PEHLE DEKHO KYA QUERY KHUD EK VIDEO ID HAI?
    video_id = None
    if len(query) == 11 and " " not in query:
        video_id = query
    elif "v=" in query:
        video_id = query.split("v=")[1].split("&")[0]
    elif "youtu.be/" in query:
        video_id = query.split("youtu.be/")[1].split("?")[0]

    # 2. AGAR ID MIL GAYI TOH PEHLE DB MEIN DHOUNDO (No YouTube Search needed)
    if video_id:
        cached_song = collection.find_one({"video_id": video_id})
        if cached_song:
            return {
                "status": "success",
                "found_in_db": True,
                "title": cached_song.get("title"),
                "download_link": cached_song["catbox_link"],
                "source": "Direct Database Cache ⚡"
            }

    # 3. AGAR ID NAHI THI YA DB MEIN NAHI MILA, TAB YOUTUBE SEARCH KARO
    try:
        search = VideosSearch(query, limit=1)
        res = search.result()['result']
        if not res:
            raise Exception("No search results")
        
        yt_id = res[0]['id']
        yt_title = res[0]['title']

        # Phir se check karo ki kya ye search wala ID DB mein hai?
        cached_song = collection.find_one({"video_id": yt_id})
        if cached_song:
            return {
                "status": "success",
                "found_in_db": True,
                "title": cached_song.get("title", yt_title),
                "download_link": cached_song["catbox_link"],
                "source": "Search Result Cache ⚡"
            }
        else:
            return {
                "status": "failed",
                "found_in_db": False,
                "message": "Gaana YT par mila par DB mein nahi hai. Pehle bot pe bajao.",
                "video_id": yt_id,
                "title": yt_title
            }
    except Exception as e:
        # Agar YouTube block hai par humare paas ID thi, toh upar hi return ho gaya hota
        # Agar yahan pahuncha hai toh search bhi fail aur ID bhi nahi thi
        raise HTTPException(status_code=404, detail="Youtube search blocked or not found.")
        
