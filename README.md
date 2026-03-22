# canva-scraper

Canva collaboration pain — quote scraper.

Python scraper that pulls Canva-related reviews from several sources and builds a **searchable static page** (`index.html`) with quotes, sources, and filters.

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

The script writes **`index.html`**, **`canva_quotes.html`** (same content), and **`canva_quotes.json`**. Set `CANVA_NO_BROWSER=1` to skip opening a browser.

## Deploy on Vercel

This repo is a **static site**: Vercel serves `index.html` at the root. The Python scraper lives entirely under **`scraper/`**, and **`.vercelignore`** excludes that folder from the deployment upload so Vercel never runs the Python builder (which would require `main.py` / `app.py`, etc.).

1. Push this folder to a **new GitHub repository** (see below).
2. Go to [vercel.com](https://vercel.com) → **Add New** → **Project** → **Import** your GitHub repo.
3. **Framework preset:** Other (or “Other” / no framework). **Build Command:** leave empty. **Output:** default / `.`
4. **Deploy**. Your site URL will be `https://<project>.vercel.app`.

After you re-run the scraper and commit updated `index.html` / `canva_quotes.json`, push to `main` — Vercel will redeploy automatically if Git integration is enabled.

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
2. Commit changes to `index.html`, `canva_quotes.html`, and `canva_quotes.json`.
3. `git push` — Vercel redeploys on push.

## License

Use at your own discretion; scraped content belongs to the original platforms and authors.
