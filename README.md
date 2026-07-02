# International Trade Research Tracker

An MVP static website that collects likely working-paper links from international trade economists' websites. The scraper uses a broad keyword heuristic, stores metadata in JSON, and leaves rendering and filtering to a small browser app.

## Add or edit economists

Edit `economists.yaml`. Each list item has five fields:

```yaml
- name: Economist Name
  field: International trade
  homepage: https://example.edu/name
  papers_url: https://example.edu/name/research
  notes: Optional maintenance note.
```

Only `name` and `papers_url` are required by the scraper. Prefer a page that lists papers directly. The other fields document the tracker and make manual maintenance easier.

## Run locally

Python 3.11 is recommended. From this directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scraper/scrape.py
python -m http.server 8000 -d site
```

Open <http://localhost:8000>. The scraper writes canonical data to `data/papers.json` and mirrors it to `site/data/papers.json` so this exact local-server command can serve it.

## Automatic updates

`.github/workflows/update.yml` runs daily, on pushes to `main`, and when started manually from the Actions tab. It installs Python 3.11 dependencies, runs the scraper, commits changed JSON, and keeps the branch-based Pages files under `docs/` synchronized.

If branch protection prevents the workflow from pushing, allow GitHub Actions to create commits or adjust the workflow to open a pull request instead.

## Deploy with GitHub Pages

The simplest deployment keeps this folder at the root of its own GitHub repository:

1. Push the repository to GitHub.
2. Open **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a branch**.
4. Select branch `main`, folder `/docs`, and click **Save**.
5. Visit `https://<account>.github.io/<repository>/` after the deployment finishes.

The published homepage is at the repository site's root. Its JavaScript reads the latest `data/papers.json` directly from `main`, so daily data commits do not need to trigger a new Pages build.

## How matching works

For every configured page, the scraper checks all HTTP(S) links and nearby text for: `paper`, `working paper`, `pdf`, `research`, `draft`, `NBER`, or `CEPR`. It resolves relative links, removes common tracking parameters, records a nearby displayed date when possible, and preserves the earliest `first_seen` date across runs. Records are deduplicated by canonical URL or by normalized title within an economist.

## Limitations

Personal websites differ widely. A broad keyword matcher can include navigation links or miss papers loaded dynamically with JavaScript. Dates are best-effort text matches, not publication-date guarantees. Some starting URLs are faculty profiles or manually supplied personal-site URLs and may move. As the tracker matures, sites with poor results may need small custom parsing rules.
