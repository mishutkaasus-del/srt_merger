# text/tools

Two text utilities in one page:
- **Text Formatter** — removes line breaks, fixes em dash spacing
- **SRT Merger** — merges SRT timing with translated subtitles

---

## Deploy to Railway (step by step)

### 1. Create a GitHub repository

1. Go to [github.com](https://github.com) and sign in (or create account)
2. Click **"New"** (green button, top left)
3. Name it e.g. `text-tools`
4. Set it to **Private** if you want
5. Click **"Create repository"**

### 2. Upload files to GitHub

After creating the repo, GitHub shows a quick-start page:

1. Click **"uploading an existing file"**
2. Drag all files from this folder INTO the GitHub window:
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `.gitignore`
   - `templates/index.html`  ← make sure to keep folder structure!
3. For `templates/index.html`: you need to create the folder on GitHub.
   - Click **"Add file → Create new file"**
   - Type `templates/index.html` in the name field — GitHub auto-creates the folder
   - Paste the content of `index.html`
4. Click **"Commit changes"**

> Easier alternative: use [GitHub Desktop](https://desktop.github.com/) to clone and drag all files in.

### 3. Deploy on Railway

1. Go to [railway.com](https://railway.com) and sign in (use GitHub login)
2. Click **"New Project"**
3. Choose **"Deploy from GitHub repo"**
4. Select your `text-tools` repo
5. Railway detects Python automatically. Click **"Deploy"**
6. Wait ~1 minute for build to finish
7. Click **"Settings → Networking → Generate Domain"**
8. Your app is live at the generated URL 🎉

### 4. Every update after that

Just push to GitHub (or edit files on github.com) — Railway auto-redeploys.

---

## Local development (optional)

```bash
pip install flask gunicorn
python app.py
# open http://localhost:5000
```
