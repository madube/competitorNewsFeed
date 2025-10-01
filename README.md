# Competitor Regulatory News → Slack

This repo posts a **weekly** summary to a Slack channel via **Incoming Webhook**. It monitors articles about **laws & regulations** that mention your competitors in your core industries from these sources:
- The Ticketing Business
- Blooloop
- IAAPA News

## What it does
- Pulls recent articles (RSS if available, or HTML fallback).
- Filters for mentions of your competitors (Accesso, RocketRez, CenterEdge, Roller) **and** industries (waterparks, theme parks, zoos, aquariums), plus legal/compliance keywords.
- De-duplicates articles using a local `data/seen.json` file.
- Posts a neatly formatted Slack message via **Incoming Webhook**.

## Quick start

1) **Create a Slack Incoming Webhook**
   - In Slack: *Apps* → **Incoming Webhooks** → Add to workspace → Select your channel → Copy the Webhook URL.
   - Save it as a GitHub secret named **SLACK_WEBHOOK_URL** (if using GitHub Actions), or an environment variable when running locally.

2) **Configure keywords & sources**
   - Edit `config.yaml` to tweak competitors, industries, and sources.
   - You can add RSS feeds or normal URLs; the script will attempt RSS first, then fallback to HTML.

3) **Run locally**
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/XXX/YYY/ZZZ'
python monitor_news.py
```

4) **Run weekly with GitHub Actions (recommended)**
   - Push these files to a new GitHub repo.
   - In the repo settings → *Secrets and variables* → *Actions* → **New repository secret**: add **SLACK_WEBHOOK_URL**.
   - The provided workflow `.github/workflows/weekly.yml` will run every **Monday at 9:00 America/Toronto** and post to Slack.

## Customizing filters
- Update `config.yaml`:
  - Expand `legal_keywords` (e.g., privacy, data protection, accessibility, payments, PCI, ADA, GDPR, CCPA).
  - Add/remove competitors or industries.
  - Add more sources with `name` and `urls`.

## Notes
- This script uses a simple heuristic filter (title/summary text). It’s intentionally conservative to reduce noise.
- If a site has no RSS, the fallback grabs page `<title>` and meta descriptions for basic filtering; you can extend the parser per source if needed.
- `data/seen.json` keeps track of what’s already posted. Delete it to reprocess from scratch.
