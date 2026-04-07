"""
ViralLab — serwer Flask
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic
import requests
import json
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

app = Flask(__name__, static_folder="static")
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/test")
def test():
    return {"status": "ok"}


# =========================
# YOUTUBE SEARCH
# =========================
@app.route("/api/youtube/search")
def youtube_search():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Brak zapytania"}), 400

    r = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 9,
            "key": YOUTUBE_API_KEY
        }
    )

    data = r.json()

    if "items" not in data:
        return jsonify({"error": "Błąd YouTube API"}), 400

    vids = []
    for v in data["items"]:
        vids.append({
            "id": v["id"]["videoId"],
            "title": v["snippet"]["title"],
            "description": v["snippet"]["description"],
            "thumbnail": v["snippet"]["thumbnails"]["medium"]["url"],
            "channel": v["snippet"]["channelTitle"]
        })

    return jsonify({"videos": vids})


# =========================
# YOUTUBE TRANSCRIPT
# =========================
@app.route("/api/youtube/transcript")
def yt_transcript():
    vid = request.args.get("video_id")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        t = YouTubeTranscriptApi.get_transcript(vid)
        text = " ".join([x["text"] for x in t])
        return {"transcript": text[:5000]}
    except:
        return {"error": "Brak transkryptu"}, 404


# =========================
# GENERATE
# =========================
@app.route("/api/generate", methods=["POST"])
def generate():
    try:
        body = request.json

        video = body.get("video", {})
        transcript = body.get("transcript", "")

        if not ANTHROPIC_API_KEY:
            return {"error": "Brak ANTHROPIC_API_KEY"}, 400

        # fallback jeśli brak transkryptu
        if not transcript:
            transcript = video.get("description", "")[:1000]

        prompt = f"""
Stwórz analizę viralową i 3 warianty skryptu.

Dane:
Tytuł: {video.get('title')}
Opis: {video.get('description')}
Treść: {transcript}

Zwróć TYLKO JSON:
{{
"analysis": {{"viralMechanism":"","emotionalTrigger":"","hookSecret":""}},
"variants":[
{{"id":1,"style":"","hook":"","cta":"","script":""}},
{{"id":2,"style":"","hook":"","cta":"","script":""}},
{{"id":3,"style":"","hook":"","cta":"","script":""}}
]
}}
"""

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = msg.content[0].text

        clean = raw.replace("```json", "").replace("```", "").strip()

        # próbuj normalnie
        try:
            return jsonify(json.loads(clean))
        except:
            pass

        # fallback regex
        try:
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                return jsonify(json.loads(match.group(0)))
        except:
            pass

        return jsonify({
            "error": "Nie udało się sparsować JSON",
            "raw": clean[:1000]
        }), 500

    except Exception as e:
        print("ERROR:", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)