# ViralLab 🔥
### YouTube → Analiza → Polski skrypt gotowy do nagrania

---

## Uruchomienie (3 kroki)

### 1. Zainstaluj zależności
```bash
pip install -r requirements.txt
```

### 2. (Opcjonalnie) Wpisz klucze API na stałe w app.py
Otwórz `app.py` i w liniach 13–14 wpisz swoje klucze:
```python
ANTHROPIC_API_KEY = "sk-ant-..."   # z console.anthropic.com
YOUTUBE_API_KEY   = "AIza..."      # z console.cloud.google.com
```
Jeśli tego nie zrobisz — wpisz klucze w formularzu przy każdym uruchomieniu.

### 3. Uruchom serwer
```bash
python app.py
```
Otwórz przeglądarkę: **http://localhost:5000**

---

## Jak uzyskać klucze API

### YouTube Data API v3 (darmowe)
1. Wejdź na https://console.cloud.google.com
2. Utwórz nowy projekt
3. W lewym menu: **Biblioteka** → wyszukaj **YouTube Data API v3** → **Włącz**
4. W lewym menu: **Dane logowania** → **Utwórz dane logowania** → **Klucz API**
5. Skopiuj klucz — gotowe!

Limit: 10 000 zapytań dziennie (wystarczy na ~500 wyszukiwań).

### Anthropic API
1. Wejdź na https://console.anthropic.com
2. Zaloguj się / zarejestruj
3. API Keys → Create Key
4. Skopiuj klucz (zaczyna się od `sk-ant-`)

---

## Jak używać

1. Wpisz klucze API w formularzu (lub na stałe w app.py)
2. Wpisz hasło lub #tag np. `#savingmoney` / `how to save money`
3. Wybierz język źródłowy i niszę docelową
4. Kliknij **Szukaj** — zobaczysz listę najpopularniejszych filmów
5. Kliknij film który Cię inspiruje → **Wybierz ten film**
6. Kliknij **Generuj polski skrypt**
7. Otrzymasz 3 skrypty: YouTube, TikTok/Reels, LinkedIn

---

## Struktura projektu
```
virallab/
├── app.py              # serwer Flask (backend)
├── requirements.txt    # zależności Python
├── README.md           # ta instrukcja
└── static/
    └── index.html      # interfejs użytkownika
```
