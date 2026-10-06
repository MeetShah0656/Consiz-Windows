# Deploy the Conciz server on Render (free)

## One-time setup
- Push this repo to GitHub (the `.env` file is git-ignored, so no secrets go up).
- Render > **New > Web Service** (or **Blueprint** to read `render.yaml`) > pick the repo.
- If you fill the form by hand:
  - Build Command: `pip install -r server/requirements.txt`
  - Start Command: `uvicorn server.app:app --host 0.0.0.0 --port $PORT`
  - Instance type: Free
- Environment variables:
  - `OPENROUTER_API_KEY` — your OpenRouter key (required)
  - `GOOGLE_CLIENT_ID` — same Desktop client ID as in your `.env` (required)
  - `PYTHON_VERSION` = `3.12.7`
  - `DATABASE_URL` — recommended, see "Keep the daily limits" below
  - `ALLOWED_EMAILS` — optional; comma-separated; empty = any verified Google account

## Check it works
- Open `https://<your-url>/health` in a browser. It should show `{"ok":true}`.
- `POST /v1/chat/completions` without sign-in must answer 401. That means it is protected.

## Keep the daily limits (important)
- The free Render disk is wiped on every restart, so with no database the daily counts reset.
- Fix for free: make a free Postgres on **neon.tech** (or any Postgres), copy its connection string,
  and set it as `DATABASE_URL` on Render. The server then keeps counts there. Nothing else to change.
- Without `DATABASE_URL` it falls back to a local SQLite file (fine for testing only).

## Limits you can tune (Render > Environment)
- `DAILY_LIMIT` (50 answers per user per day), `IP_DAILY_LIMIT` (300 per network per day),
  `RATE_PER_MIN` (12 per user), `MAX_INPUT_CHARS` (40000), `MAX_MESSAGES` (30),
  `MAX_OUTPUT_TOKENS` (5000), `OPENROUTER_MODEL`, `OPENROUTER_FALLBACKS`.
- If the AI provider fails, the user's answer is not counted.

## Point the app at it
- In each user's `.env`: `CONSIZ_SERVER_URL=https://<your-url>`
- For the exe: put it in your `.env`, then run `python build_exe.py` — it bakes the URL and the Google
  client ID in. The OpenRouter key is never baked in.

## Google consent screen (do this before real users)
- Google Cloud Console > Google Auth Platform > **Audience** > **Publish app** (In production).
- While it says "Testing": only listed test users can sign in, and sign-ins expire after 7 days.
- Basic sign-in (email + profile) needs no Google review.

## Good to know (free plan)
- The server sleeps after ~15 min idle. The first answer after a pause takes 30-60 s.
  The app waits up to 100 s, retries 3 times, and wakes the server at startup.
- For real users: the paid always-on plan (about $7/month) removes the sleep.
