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
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__, static_folder="static")
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/test", methods=["GET"])
def api_test():
    return jsonify({"status": "ok"})


# =========================
# YOUTUBE SEARCH
# =========================
@app.route("/api/youtube/search", methods=["GET"])
def youtube_search():
    query = request.args.get("q", "").strip()
    order = request.args.get("order", "viewCount").strip()
    lang = request.args.get("lang", "en").strip()
    max_results = request.args.get("maxResults", "9").strip()

    if not YOUTUBE_API_KEY:
        return jsonify({"error": "Brak YOUTUBE_API_KEY w Render Environment Variables"}), 400

    if not query:
        return jsonify({"error": "Brak zapytania"}), 400

    allowed_orders = {"viewCount", "relevance", "date"}
    if order not in allowed_orders:
        order = "viewCount"

    try:
        max_results_int = int(max_results)
    except Exception:
        max_results_int = 9

    max_results_int = max(1, min(max_results_int, 25))

    try:
        # 1. search.list
        search_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query.lstrip("#"),
                "type": "video",
                "order": order,
                "relevanceLanguage": lang,
                "maxResults": max_results_int,
                "key": YOUTUBE_API_KEY,
            },
            timeout=20,
        )
        search_data = search_resp.json()

        if "error" in search_data:
            return jsonify({"error": search_data["error"].get("message", "Błąd YouTube API")}), 400

        items = search_data.get("items", [])
        if not items:
            return jsonify({"error": "Brak wyników"}), 404

        video_ids = [
            item.get("id", {}).get("videoId")
            for item in items
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return jsonify({"error": "Brak prawidłowych identyfikatorów filmów"}), 404

        # 2. videos.list ze statystykami
        videos_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "statistics,contentDetails,snippet",
                "id": ",".join(video_ids),
                "key": YOUTUBE_API_KEY,
            },
            timeout=20,
        )
        videos_data = videos_resp.json()
        stats_map = {v["id"]: v for v in videos_data.get("items", [])}

        result = []
        for item in items:
            vid = item["id"]["videoId"]
            sn = item.get("snippet", {})
            st = stats_map.get(vid, {})

            result.append({
                "id": vid,
                "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "channel": sn.get("channelTitle", ""),
                "thumbnail": (sn.get("thumbnails") or {}).get("medium", {}).get("url", ""),
                "published": sn.get("publishedAt", "")[:10],
                "views": st.get("statistics", {}).get("viewCount", "0"),
                "likes": st.get("statistics", {}).get("likeCount", "0"),
                "duration": st.get("contentDetails", {}).get("duration", ""),
                "tags": st.get("snippet", {}).get("tags", [])[:10],
            })

        return jsonify({"videos": result})

    except Exception as e:
        return jsonify({"error": f"Błąd YouTube API: {str(e)}"}), 500


# =========================
# YOUTUBE TRANSCRIPT
# =========================
@app.route("/api/youtube/transcript", methods=["GET"])
def youtube_transcript():
    video_id = request.args.get("video_id", "").strip()
    lang = request.args.get("lang", "en").strip()

    if not video_id:
        return jsonify({"error": "Brak video_id"}), 400

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        full_text = None

        try:
            transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang, "en"])
            full_text = " ".join(x["text"] for x in transcript_data)
        except Exception:
            full_text = None

        if not full_text:
            return jsonify({"error": "Brak dostępnych napisów dla tego filmu"}), 404

        full_text = full_text[:8000]

        return jsonify({
            "transcript": full_text,
            "length": len(full_text),
            "is_generated": True
        })

    except Exception:
        return jsonify({"error": "Brak transkryptu"}), 404


# =========================
# TIKTOK SEARCH (APIFY)
# =========================
@app.route("/api/tiktok/apify-search", methods=["GET"])
def tiktok_apify_search():
    query = request.args.get("q", "").strip()
    max_r = request.args.get("maxResults", "9").strip()

    if not query:
        return jsonify({"error": "Brak zapytania"}), 400

    if not APIFY_TOKEN:
        return jsonify({"error": "Brak APIFY_TOKEN w Render Environment Variables"}), 400

    try:
        max_r_int = int(max_r)
    except Exception:
        max_r_int = 9

    max_r_int = max(1, min(max_r_int, 20))

    try:
        run_url = "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs"
        payload = {
            "hashtags": [query.lstrip("#")],
            "resultsPerPage": max_r_int,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": True,
        }
        headers = {
            "Authorization": f"Bearer {APIFY_TOKEN}",
            "Content-Type": "application/json",
        }

        start_resp = requests.post(run_url, json=payload, headers=headers, timeout=20)
        start_data = start_resp.json()

        if "error" in start_data:
            return jsonify({"error": start_data["error"].get("message", "Błąd Apify")}), 400

        run_id = start_data.get("data", {}).get("id")
        if not run_id:
            return jsonify({"error": "Nie udało się uruchomić aktora Apify"}), 400

        dataset_id = None

        for _ in range(15):
            time.sleep(2)
            status_resp = requests.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers=headers,
                timeout=15,
            )
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status", "")

            if status == "SUCCEEDED":
                dataset_id = status_data.get("defaultDatasetId")
                break

            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return jsonify({"error": f"Aktor Apify zakończył się błędem: {status}"}), 400

        if not dataset_id:
            return jsonify({"error": "Timeout — Apify nie zwróciło wyników w czasie. Spróbuj ponownie."}), 400

        items_resp = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?limit={max_r_int}",
            headers=headers,
            timeout=15,
        )
        items = items_resp.json()

        if not items:
            return jsonify({"error": "Brak wyników dla tego hasła"}), 404

        results = []
        for item in items[:max_r_int]:
            results.append({
                "id": str(item.get("id", "")),
                "title": (item.get("text", "") or item.get("desc", ""))[:120],
                "description": item.get("text", "") or item.get("desc", ""),
                "author": item.get("authorMeta", {}).get("name", "") or item.get("author", {}).get("uniqueId", ""),
                "thumbnail": item.get("covers", {}).get("default", "") or item.get("videoMeta", {}).get("coverUrl", ""),
                "views": str(item.get("playCount", item.get("stats", {}).get("playCount", "0"))),
                "likes": str(item.get("diggCount", item.get("stats", {}).get("diggCount", "0"))),
                "duration": str(item.get("videoMeta", {}).get("duration", "")),
                "source_url": item.get("webVideoUrl", ""),
            })

        return jsonify({"videos": results})

    except Exception as e:
        return jsonify({"error": f"Błąd połączenia z Apify: {str(e)}"}), 500


# =========================
# TIKTOK FETCH FROM URL
# =========================
@app.route("/api/tiktok/fetch", methods=["GET"])
def tiktok_fetch():
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify({"error": "Brak URL"}), 400

    if not RAPIDAPI_KEY:
        return jsonify({"error": "Brak RAPIDAPI_KEY w Render Environment Variables"}), 400

    try:
        r = requests.get(
            "https://tiktok-api23.p.rapidapi.com/api/detail",
            params={"url": url},
            headers={
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": "tiktok-api23.p.rapidapi.com",
            },
            timeout=15,
        )
        d = r.json()
        item = d.get("itemInfo", {}).get("itemStruct", {})

        if item:
            desc = item.get("desc", "")
            stats = item.get("stats", {})
            author = item.get("author", {})
            return jsonify({
                "platform": "tiktok",
                "title": desc[:100],
                "description": desc,
                "author": author.get("nickname", ""),
                "thumbnail": item.get("video", {}).get("cover", ""),
                "views": str(stats.get("playCount", "0")),
                "likes": str(stats.get("diggCount", "0")),
                "source_url": url,
            })

    except Exception:
        pass

    return jsonify({"error": "Nie udało się pobrać danych. Sprawdź link i klucz RapidAPI."}), 400


# =========================
# GENERATE SCRIPT
# =========================
@app.route("/api/generate", methods=["POST"])
def generate_script():
    try:
        body = request.get_json(silent=True) or {}

        video = body.get("video", {})
        transcript = body.get("transcript", "")
        niche = body.get("niche", "ogólna")
        src_lang = body.get("srcLang", "en")

        if not ANTHROPIC_API_KEY:
            return jsonify({"error": "Brak ANTHROPIC_API_KEY w Render Environment Variables"}), 400

        if not video:
            return jsonify({"error": "Brak danych filmu"}), 400

        description = (video.get("description") or "").strip()
        tags = video.get("tags") or []
        title = (video.get("title") or "").strip()
        channel = (video.get("channel") or video.get("author") or "").strip()

        if transcript and transcript.strip():
            source_block = f"PEŁNY TRANSKRYPT:\n{transcript.strip()[:8000]}"
        else:
            fallback_parts = []

            if description:
                fallback_parts.append(f"OPIS FILMU:\n{description[:1200]}")
            if tags:
                fallback_parts.append(f"TAGI:\n{', '.join(tags[:15])}")
            if title:
                fallback_parts.append(f"TYTUŁ:\n{title}")
            if channel:
                fallback_parts.append(f"AUTOR/KANAŁ:\n{channel}")

            if not fallback_parts:
                fallback_parts.append("Brak transkryptu, opisu i tagów. Oprzyj się na samych metadanych filmu.")

            source_block = (
                "BRAK DOSTĘPNEGO TRANSKRYPTU. "
                "Użyj opisu, tytułu, tagów i metadanych filmu.\n\n"
                + "\n\n".join(fallback_parts)
            )

        prompt = f"""
Jesteś ekspertem od viralowego contentu i copywriterem z 15-letnim doświadczeniem w Polsce.

ORYGINALNY FILM:
- Tytuł: {title}
- Kanał/Autor: {channel}
- Język oryginału: {src_lang}
- Nisza docelowa PL: {niche}

{source_block}

Na podstawie materiału przygotuj analizę i 3 warianty polskiego skryptu.

Zwróć WYŁĄCZNIE poprawny JSON.
Nie dodawaj żadnego komentarza, markdownu, bloków ``` ani tekstu przed lub po JSON.

Struktura JSON:
{{
  "analysis": {{
    "viralMechanism": "",
    "emotionalTrigger": "",
    "hookSecret": ""
  }},
  "variants": [
    {{
      "id": 1,
      "style": "Emocjonalny",
      "styleDesc": "Osobista historia, emocje, storytelling",
      "hook": "",
      "cta": "",
      "script": ""
    }},
    {{
      "id": 2,
      "style": "Edukacyjny",
      "styleDesc": "Fakty, dane, wiedza krok po kroku",
      "hook": "",
      "cta": "",
      "script": ""
    }},
    {{
      "id": 3,
      "style": "Prowokacyjny",
      "styleDesc": "Kontrowersja, zaskoczenie, obalenie mitu",
      "hook": "",
      "cta": "",
      "script": ""
    }}
  ]
}}
"""

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1400,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = msg.content[0].text if msg.content else ""
        clean = raw.strip()
        clean = clean.replace("```json", "").replace("```", "").strip()

        # próba 1: czysty JSON
        try:
            return jsonify(json.loads(clean))
        except Exception:
            pass

        # próba 2: wytnij od pierwszego { do ostatniego }
        try:
            start = clean.find("{")
            end = clean.rfind("}") + 1
            if start != -1 and end > start:
                sliced = clean[start:end]
                return jsonify(json.loads(sliced))
        except Exception:
            pass

        # próba 3: regex
        try:
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                return jsonify(json.loads(match.group(0)))
        except Exception:
            pass

        return jsonify({
            "error": "Model zwrócił odpowiedź w niepoprawnym formacie JSON",
            "raw": clean[:2000]
        }), 500

    except Exception as e:
        print("GENERATE ERROR:", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("\n🚀 ViralLab uruchomiony lokalnie")
    print(f" YouTube API: {'✓' if YOUTUBE_API_KEY else '✗ BRAK'}")
    print(f" Anthropic API: {'✓' if ANTHROPIC_API_KEY else '✗ BRAK'}")
    print(f" RapidAPI: {'✓' if RAPIDAPI_KEY else '✗ BRAK'}")
    print(f" Apify: {'✓' if APIFY_TOKEN else '✗ BRAK'}\n")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)