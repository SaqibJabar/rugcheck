# Deploying rugcheck to Railway.app

This guide shows how to deploy the `rugcheck` FastAPI app to Railway and get a public URL.

Prerequisites
- A GitHub account
- Railway account (https://railway.app)
- The project in a local Git repository with the code committed

Required environment variables (set these in Railway after creating the project):
- `GROQ_API_KEY` — Groq API key
- `ETHERSCAN_API_KEY` — Etherscan API key (optional but recommended)

Files added for deployment
- `Procfile` — `web: uvicorn main:app --host 0.0.0.0 --port $PORT`

Quick steps (web UI)
1. Push your repo to GitHub:

```bash
git add .
git commit -m "Prepare for Railway deploy: add Procfile and deploy README"
git push origin main
```

2. Go to https://railway.app and create a new project → "Deploy from GitHub".
3. Select your repository and the branch (e.g., `main`). Railway will detect Python and install dependencies from `requirements.txt`.
4. In Railway project settings, set environment variables `GROQ_API_KEY` and `ETHERSCAN_API_KEY`.
5. Trigger a deploy. After build completes, Railway will provide a public URL (copy it).

Railway CLI option
1. Install Railway CLI: https://docs.railway.app/cli
2. From your repo root run:

```bash
railway login
railway init            # create project or link to existing
railway up              # deploy current repo
```

Notes
- Ensure `.env` is not committed. Keep keys only in Railway environment variables.
- If your app requires a different start command, update the `Procfile` accordingly.

If you want, I can:
- Create a Git commit for you in this workspace (if you want me to run git commands here).
- Walk through connecting the repo to Railway step-by-step while you authorize.
