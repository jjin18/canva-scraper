# canva-scraper

Canva collaboration pain — quote scraper.

Python scraper that pulls Canva-related reviews from several sources and builds a **searchable static page** (`site/index.html`) with quotes, sources, and filters.

## Run locally

**Use the folder that contains `README.md` and `scraper/`** (for you that is usually `canva-collab-scraper`). If you run commands from `C:\Users\jiahu` or your Desktop, Python will not find `scraper/requirements.txt`.

**Windows (PowerShell):**

```powershell
cd C:\Users\jiahu\canva-collab-scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scraper/requirements.txt
$env:PYTHONUTF8 = "1"
python scraper\canva_scraper.py
```

**Same steps in bash (after `cd` into the repo):**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r scraper/requirements.txt
set PYTHONUTF8=1
python scraper/canva_scraper.py
```

On macOS/Linux, use `source .venv/bin/activate` and `export PYTHONUTF8=1`.

The script writes **`site/index.html`**, **`site/canva_quotes.html`** (same content), and **`site/canva_quotes.json`**. Set `CANVA_NO_BROWSER=1` to skip opening a browser.

## Deploy on Vercel (static only — no Python)

Vercel only deploys the **`site/`** folder. There is **no** build step and **no** Python on Vercel; the scraper runs on your machine only.

1. Import the GitHub repo in [Vercel](https://vercel.com).
2. Open **Project → Settings → General**.
3. Set **Root Directory** to **`site`** (required — this avoids “No python entrypoint” from the rest of the repo).
4. **Framework preset:** Other. **Build Command:** leave empty. **Install Command:** leave empty (or `echo skip`).
5. Save and **Redeploy**.

Your live URL serves `site/index.html` as `/`.

After you re-run the scraper, commit and push changes under **`site/`** so the deployment updates.

## Push to GitHub (first time)

Replace `YOUR_USER` and `YOUR_REPO` with your GitHub username and repository name.

```bash
cd canva-collab-scraper
git init
git add .
git commit -m "Initial commit: Canva quotes scraper and static site"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

Create an empty repo on GitHub first (**without** a README, so you can push cleanly), or use **GitHub Desktop** / **Cursor’s Source Control** to publish the folder.

## Updating the live site

1. Run `python scraper/canva_scraper.py` from the repo root.
2. Commit changes under **`site/`** (`index.html`, `canva_quotes.html`, `canva_quotes.json`).
3. `git push` — Vercel redeploys on push.

## License

Use at your own discretion; scraped content belongs to the original platforms and authors.
