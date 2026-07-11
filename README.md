# YouTube Playlist Auto-Categorizer

Sorts videos from one YouTube playlist into category playlists, using a
local LLM (via LM Studio) to read each video's title/description/tags and
decide which category fits. Videos the model isn't confident about are
queued for you to review interactively at the end. Nothing about the video
content leaves your machine except the metadata YouTube's API already
returns to you — categorization runs entirely against your local LM Studio
server, using structured JSON output so the model can only ever answer with
one of your actual category names.

## 1. Prerequisites

- Python 3.10+
- LM Studio, with a model downloaded and the local server running:
  1. Open LM Studio, download/load a model (e.g. a Qwen2.5 7B instruct GGUF)
  2. Go to the **Developer** tab and click **Start Server** (defaults to
     `http://localhost:1234`), or run `lms server start` from the CLI
  3. Leave `model: ""` in `config.yaml` to auto-use whatever's loaded, or
     set an exact model id (check `lms ls` or `GET /v1/models`)
- A Google Cloud project with the **YouTube Data API v3** enabled, and an
  OAuth **Desktop app** client:
  1. https://console.cloud.google.com/ → create/select a project
  2. APIs & Services → Library → enable "YouTube Data API v3"
  3. APIs & Services → Credentials → Create Credentials → OAuth client ID →
     Application type "Desktop app"
  4. Download the JSON, save it as `client_secret.json` in this folder
  5. On the OAuth consent screen, add your own Google account as a test
     user (unless you've published the app)

## 2. Install

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
cp config.example.yaml config.yaml
```

Edit `config.yaml`:
- `youtube.source_playlist_id` — the playlist you want sorted (grab the ID
  from the playlist's URL, `...list=PLxxxxxxxx`)
- `categories` — your real categories. Write a specific one-line
  `description` for each; this is what the LLM uses to disambiguate, so
  vague descriptions lead to more videos landing in manual review.
- `youtube.remove_from_source` — `true` to actually move videos out of the
  source playlist, `false` to just copy them into the category playlists
  and leave the source untouched.

## 3. Run

First run will open a browser to authorize access — do a small dry run first:

```bash
python3 main.py --dry-run --limit 5
```

Check the console output looks sensible, then run for real:

```bash
python3 main.py
```

At the end, videos the model wasn't confident about are listed with a
prompt to pick a category yourself (or skip and leave them in place).

Re-running the script later only processes videos not already recorded in
`processed.json`, so it's safe to stop and resume, or add new videos to the
source playlist and re-run.

## Notes on YouTube API quota

The default daily quota is 10,000 units. Rough costs: listing playlist
pages and video details are cheap (~1 unit each), but each move costs
~100 units (`playlistItems.insert` = 50, `playlistItems.delete` = 50). That
caps you around ~100 moves/day on the default quota — for a big backlog,
run it in batches across a few days, or request a quota increase in the
Cloud Console.

## Files

| File | Purpose |
|---|---|
| `main.py` | Orchestrates the whole run |
| `auth.py` | OAuth2 login/token caching |
| `youtube_api.py` | YouTube Data API calls |
| `lm_studio_client.py` | Calls your local LM Studio server |
| `categorizer.py` | Builds the prompt/JSON schema, parses the LLM's answer |
| `state.py` | Tracks processed videos for safe resuming |
| `config.example.yaml` | Template — copy to `config.yaml` |
