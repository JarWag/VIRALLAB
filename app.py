"""
ViralLab — serwer Flask
Uruchom: python app.py
Otwórz:  http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic
import requests
import json
import os

# Wczytaj klucze z pliku .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__, static_folder="static")
CORS(app)

# Klucze API — czytane z .env automatycznie
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY   = os.environ.get("YOUTUBE_API_KEY", "")
RAPIDAPI_KEY      = os.environ.get("RAPIDAPI_KEY", "")
APIFY_TOKEN       = os.environ.get("APIFY_TOKEN", "")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── YouTube: wyszukiwanie ──
@app.route("/api/youtube/search")
def youtube_search():
    yt_key = YOUTUBE_API_KEY
    query  = request.args.get("q", "")
    order  = request.args.get("order", "relevance")
    lang   = request.args.get("lang", "en")
    max_r  = request.args.get("maxResults", "9")

    if not yt_key: return jsonify({"error": "Brak klucza YouTube API w pliku .env"}), 400
    if not query:  return jsonify({"error": "Brak zapytania"}), 400

    r = requests.get("https://www.googleapis.com/youtube/v3/search", params={
        "part": "snippet", "q": query.lstrip("#"), "type": "video",
        "order": order, "relevanceLanguage": lang, "maxResults": max_r, "key": yt_key
    }, timeout=10)
    data = r.json()

    if "error" in data: return jsonify({"error": data["error"]["message"]}), 400
    items = data.get("items", [])
    if not items: return jsonify({"error": "Brak wyników"}), 404

    ids = ",".join(i["id"]["videoId"] for i in items)
    rs  = requests.get("https://www.googleapis.com/youtube/v3/videos", params={
        "part": "statistics,contentDetails,snippet", "id": ids, "key": yt_key
    }, timeout=10)
    stats_map = {v["id"]: v for v in rs.json().get("items", [])}

    result = []
    for item in items:
        vid = item["id"]["videoId"]
        sn  = item["snippet"]
        st  = stats_map.get(vid, {})
        result.append({
            "id":          vid,
            "title":       sn.get("title", ""),
            "description": sn.get("description", ""),
            "channel":     sn.get("channelTitle", ""),
            "thumbnail":   (sn.get("thumbnails") or {}).get("medium", {}).get("url", ""),
            "published":   sn.get("publishedAt", "")[:10],
            "views":       st.get("statistics", {}).get("viewCount", "0"),
            "likes":       st.get("statistics", {}).get("likeCount", "0"),
            "duration":    st.get("contentDetails", {}).get("duration", ""),
            "tags":        st.get("snippet", {}).get("tags", [])[:10],
        })
    return jsonify({"videos": result})


# ── YouTube: transkrypt ──
@app.route("/api/youtube/transcript")
def youtube_transcript():
    video_id = request.args.get("video_id", "")
    lang     = request.args.get("lang", "en")
    if not video_id: return jsonify({"error": "Brak video_id"}), 400

    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        full_text = None
        language_code = lang
        is_generated = True

        # Próba 1: nowe API (>= 0.7)
        try:
            for try_lang in [lang, "en"]:
                try:
                    result = YouTubeTranscriptApi.fetch(video_id, languages=[try_lang])
                    snippets = result if isinstance(result, list) else list(result)
                    full_text = " ".join(
                        (s.get("text") if isinstance(s, dict) else s.text)
                        for s in snippets
                    )
                    language_code = try_lang
                    break
                except Exception:
                    continue
        except Exception:
            pass

        # Próba 2: stare API (< 0.7)
        if not full_text:
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = None
                for try_lang in [lang, "en", None]:
                    try:
                        transcript = transcript_list.find_transcript([try_lang]) if try_lang else next(iter(transcript_list))
                        break
                    except Exception:
                        continue
                if transcript:
                    data = transcript.fetch()
                    full_text = " ".join(entry["text"] for entry in data)
                    language_code = transcript.language_code
                    is_generated = transcript.is_generated
            except Exception:
                pass

        # Próba 3: get_transcript
        if not full_text:
            try:
                result = YouTubeTranscriptApi.get_transcript(video_id)
                full_text = " ".join(entry["text"] for entry in result)
            except Exception:
                pass

        if not full_text:
            return jsonify({"error": "Brak dostępnych napisów dla tego filmu"}), 404

        if len(full_text) > 8000:
            full_text = full_text[:8000] + "..."

        return jsonify({
            "transcript":   full_text,
            "language":     language_code,
            "is_generated": is_generated,
            "length":       len(full_text)
        })

    except ImportError:
        return jsonify({"error": "Uruchom: pip install youtube-transcript-api"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── TikTok: wyszukiwanie przez Apify ──
@app.route("/api/tiktok/search")
def tiktok_search():
    query       = request.args.get("q", "").strip()
    max_r       = int(request.args.get("maxResults", "9"))
    apify_token = request.args.get("apify_token") or APIFY_TOKEN

    if not query:       return jsonify({"error": "Brak zapytania"}), 400
    if not apify_token: return jsonify({"error": "Brak tokenu Apify — dodaj APIFY_TOKEN do pliku .env"}), 400

    try:
        # Uruchom aktora TikTok Scraper na Apify
        run_url = "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs"
        payload = {
            "hashtags": [query.lstrip("#")],
            "resultsPerPage": max_r,
            "searchSection": "/search/video",
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        }
        headers = {"Authorization": f"Bearer {apify_token}", "Content-Type": "application/json"}

        # Start run
        r = requests.post(run_url, json=payload, headers=headers, timeout=15)
        run_data = r.json()

        if r.status_code != 201:
            msg = run_data.get("error", {}).get("message", "Błąd Apify")
            return jsonify({"error": f"Apify: {msg}"}), 400

        run_id      = run_data["data"]["id"]
        dataset_id  = run_data["data"]["defaultDatasetId"]

        # Czekaj na zakończenie (max 60 sek)
        import time
        for _ in range(30):
            time.sleep(2)
            status_r = requests.get(
                f"https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs/{run_id}",
                headers=headers, timeout=10
            )
            status = status_r.json().get("data", {}).get("status", "")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

        if status != "SUCCEEDED":
            return jsonify({"error": "Apify nie ukończył wyszukiwania — spróbuj ponownie"}), 400

        # Pobierz wyniki
        items_r = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?limit={max_r}",
            headers=headers, timeout=10
        )
        items = items_r.json()

        if not items:
            return jsonify({"error": "Brak wyników dla tego hasła"}), 404

        results = []
        for item in items[:max_r]:
            results.append({
                "id":          str(item.get("id", "")),
                "title":       str(item.get("text", ""))[:120],
                "description": str(item.get("text", "")),
                "author":      str(item.get("authorMeta", {}).get("name", "")),
                "thumbnail":   str(item.get("covers", {}).get("default", "")),
                "views":       str(item.get("playCount", "0")),
                "likes":       str(item.get("diggCount", "0")),
                "duration":    str(item.get("videoMeta", {}).get("duration", "")),
                "source_url":  str(item.get("webVideoUrl", ""))
            })

        return jsonify({"videos": results})

    except Exception as e:
        return jsonify({"error": f"Błąd połączenia z Apify: {str(e)}"}), 500




# ── TikTok: wyszukiwanie przez Apify ──
@app.route("/api/tiktok/apify-search")
def tiktok_apify_search():
    query     = request.args.get("q", "").strip()
    max_r     = int(request.args.get("maxResults", "9"))
    token     = request.args.get("apify_token") or APIFY_TOKEN

    if not query: return jsonify({"error": "Brak zapytania"}), 400
    if not token: return jsonify({"error": "Brak tokenu Apify — dodaj APIFY_TOKEN do pliku .env"}), 400

    try:
        # Uruchom aktora TikTok Scraper na Apify
        run_url = "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs"
        payload = {
            "hashtags": [query.lstrip("#")],
            "resultsPerPage": max_r,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": True,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Start run
        r = requests.post(run_url, json=payload, headers=headers, timeout=15)
        run_data = r.json()

        if "error" in run_data:
            return jsonify({"error": run_data["error"].get("message", "Błąd Apify")}), 400

        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            return jsonify({"error": "Nie udało się uruchomić aktora Apify"}), 400

        # Czekaj na wyniki (max 30 sekund)
        import time
        dataset_id = None
        for _ in range(15):
            time.sleep(2)
            status_r = requests.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                headers=headers, timeout=10
            )
            status_d = status_r.json().get("data", {})
            status = status_d.get("status", "")
            if status == "SUCCEEDED":
                dataset_id = status_d.get("defaultDatasetId")
                break
            elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return jsonify({"error": f"Aktor Apify zakończył się błędem: {status}"}), 400

        if not dataset_id:
            return jsonify({"error": "Timeout — Apify nie zwróciło wyników w czasie. Spróbuj ponownie."}), 400

        # Pobierz wyniki
        items_r = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?limit={max_r}",
            headers=headers, timeout=10
        )
        items = items_r.json()

        if not items:
            return jsonify({"error": "Brak wyników dla tego hasła"}), 404

        results = []
        for item in items[:max_r]:
            results.append({
                "id":          item.get("id", ""),
                "title":       (item.get("text", "") or item.get("desc", ""))[:120],
                "description": item.get("text", "") or item.get("desc", ""),
                "author":      item.get("authorMeta", {}).get("name", "") or item.get("author", {}).get("uniqueId", ""),
                "thumbnail":   item.get("covers", {}).get("default", "") or item.get("videoMeta", {}).get("coverUrl", ""),
                "views":       str(item.get("playCount", item.get("stats", {}).get("playCount", "0"))),
                "likes":       str(item.get("diggCount", item.get("stats", {}).get("diggCount", "0"))),
                "duration":    str(item.get("videoMeta", {}).get("duration", "")),
                "source_url":  item.get("webVideoUrl", "")
            })

        return jsonify({"videos": results})

    except Exception as e:
        return jsonify({"error": f"Błąd połączenia z Apify: {str(e)}"}), 500

# ── TikTok: pobierz dane z linku ──
@app.route("/api/tiktok/fetch")
def tiktok_fetch():
    url       = request.args.get("url", "").strip()
    rapid_key = request.args.get("rapid_key") or RAPIDAPI_KEY

    if not url:       return jsonify({"error": "Brak URL"}), 400
    if not rapid_key: return jsonify({"error": "Brak klucza RapidAPI — dodaj RAPIDAPI_KEY do pliku .env"}), 400

    try:
        r = requests.get(
            "https://tiktok-api23.p.rapidapi.com/api/detail",
            params={"url": url},
            headers={"X-RapidAPI-Key": rapid_key, "X-RapidAPI-Host": "tiktok-api23.p.rapidapi.com"},
            timeout=10
        )
        d = r.json()
        item = d.get("itemInfo", {}).get("itemStruct", {})
        if item:
            desc   = item.get("desc", "")
            stats  = item.get("stats", {})
            author = item.get("author", {})
            return jsonify({
                "platform":    "tiktok",
                "title":       desc[:100],
                "description": desc,
                "author":      author.get("nickname", ""),
                "thumbnail":   item.get("video", {}).get("cover", ""),
                "views":       str(stats.get("playCount", "0")),
                "likes":       str(stats.get("diggCount", "0")),
                "source_url":  url
            })
    except Exception:
        pass

    return jsonify({"error": "Nie udało się pobrać danych. Sprawdź link i klucz RapidAPI."}), 400


# ── Claude: generuj 3 warianty skryptu ──
@app.route("/api/generate", methods=["POST"])
def generate_script():
    body       = request.get_json()
    video      = body.get("video", {})
    niche      = body.get("niche", "ogólna")
    src_lang   = body.get("srcLang", "en")
    transcript = body.get("transcript", "")
    ant_key    = ANTHROPIC_API_KEY

    if not ant_key: return jsonify({"error": "Brak klucza Anthropic API w pliku .env"}), 400

    lang_names = {"en":"angielski","de":"niemiecki","es":"hiszpański","fr":"francuski","it":"włoski"}

    def fmt(n):
        n = int(n or 0)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.0f}K"
        return str(n)

    if transcript:
        source_section = f"PEŁNY TRANSKRYPT ORYGINAŁU:\n{transcript}"
    else:
        source_section = f"OPIS FILMU (brak transkryptu):\n{video.get('description','')[:800]}\nTagi: {', '.join(video.get('tags',[]))}"

    prompt = f"""Jesteś ekspertem od viralowego contentu i copywriterem z 15-letnim doświadczeniem w Polsce.

ORYGINALNY FILM:
- Tytuł: {video.get('title','')}
- Kanał/Autor: {video.get('channel', video.get('author',''))}
- Wyświetlenia: {fmt(video.get('views',0))}
- Język oryginału: {lang_names.get(src_lang,'angielski')}
- Nisza docelowa PL: {niche}

{source_section}

TWOJE ZADANIE:
Na podstawie oryginału stwórz 3 WARIANTY polskiego skryptu + wersje dla każdej platformy.

ZASADY ADAPTACJI:
- Zamień realia zagraniczne na polskie (Walmart→Biedronka/Lidl, $→zł, itp.)
- Zachowaj mechanizm wiralności oryginału
- Skrypt ma brzmieć naturalnie po polsku, NIE jak tłumaczenie

WARIANTY:
- Wariant 1 EMOCJONALNY: osobista historia, storytelling, emocje
- Wariant 2 EDUKACYJNY: fakty, dane, kroki, konkretna wiedza
- Wariant 3 PROWOKACYJNY: kontrowersja, obalenie mitu, zaskoczenie

Odpowiedz TYLKO JSON bez markdown:
{{
  "analysis": {{
    "viralMechanism": "Co sprawia że oryginał działa (2-3 zdania)",
    "emotionalTrigger": "Główna emocja",
    "hookSecret": "Dlaczego pierwsze 3 sekundy zatrzymują widza"
  }},
  "variants": [
    {{
      "id": 1,
      "style": "Emocjonalny",
      "styleDesc": "Osobista historia, emocje, storytelling",
      "hook": "Pierwsze zdanie zatrzymujące widza (max 120 znaków)",
      "cta": "Call to action na końcu",
      "script": "Pełny skrypt 400-600 słów. Sekcje: WSTĘP / ROZWINIĘCIE / ZAKOŃCZENIE. Didaskalia: [PAUZA] [ZBLIŻENIE] [TEKST NA EKRANIE: xxx]"
    }},
    {{
      "id": 2,
      "style": "Edukacyjny",
      "styleDesc": "Fakty, dane, wiedza krok po kroku",
      "hook": "Pierwsze zdanie (max 120 znaków)",
      "cta": "Call to action",
      "script": "Pełny skrypt 400-600 słów z didaskaliami i sekcjami."
    }},
    {{
      "id": 3,
      "style": "Prowokacyjny",
      "styleDesc": "Kontrowersja, zaskoczenie, obalenie mitu",
      "hook": "Pierwsze zdanie (max 120 znaków)",
      "cta": "Call to action",
      "script": "Pełny skrypt 400-600 słów z didaskaliami i sekcjami."
    }}
  ],
  "platforms": {{
    "youtube": {{
      "recommendedVariant": 1,
      "title": "Tytuł YouTube max 70 znaków",
      "description": "Opis pod filmem 150-200 słów z hashtagami",
      "tags": ["tag1","tag2","tag3","tag4","tag5"],
      "estimatedDuration": "np. 6-8 minut"
    }},
    "tiktok": {{
      "recommendedVariant": 3,
      "title": "Caption max 50 znaków",
      "shortScript": "Skrypt TikTok max 60 sek / 150-200 słów. Bardzo dynamiczny z [CUT].",
      "hook": "Pierwsze 2 sekundy",
      "cta": "CTA TikTok",
      "tags": ["#tag1","#tag2","#tag3","#tag4","#tag5"]
    }},
    "linkedin": {{
      "recommendedVariant": 2,
      "title": "Nagłówek posta",
      "post": "Treść posta 200-300 słów. Profesjonalny ton, akapity 1-2 zdania.",
      "hook": "Pierwsze zdanie zatrzymujące scrollowanie",
      "cta": "Pytanie do dyskusji",
      "tags": ["#tag1","#tag2","#tag3"]
    }}
  }}
}}"""

    client  = anthropic.Anthropic(api_key=ant_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    raw   = message.content[0].text
    clean = raw.replace("```json", "").replace("```", "").strip()
    return jsonify(json.loads(clean))


@app.route("/api/test", methods=["GET"])
def api_test():
    return {"status": "ok"}


if __name__ == "__main__":
    print("\n🚀 ViralLab uruchomiony → http://localhost:5000")
    print(f" YouTube API: {'✓' if YOUTUBE_API_KEY else '✗ BRAK — dodaj do .env'}")
    print(f" Anthropic API: {'✓' if ANTHROPIC_API_KEY else '✗ BRAK — dodaj do .env'}")
    print(f" RapidAPI: {'✓' if RAPIDAPI_KEY else '✗ BRAK — dodaj do .env (potrzebne dla TikTok)'}\n")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)