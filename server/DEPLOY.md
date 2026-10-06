# Deploy the Conciz server on Render (free)

## One-time setup
- Push this repo to GitHub (the `.env` file is git-ignored, so no secrets go up).
- Go to render.com > **New > Blueprint** > pick the repo. Render reads `render.yaml`.
- When asked for secret values, fill in:
  - `OPENROUTER_API_KEY` — your OpenRouter key
  - `GOOGLE_CLIENT_ID` — same Desktop client ID as in your `.env`
  - `ALLOWED_EMAILS` — optional; leave empty to allow any verified Google account
- Click **Apply**. Wait for "Live". You get a URL like `https://conciz-server.onrender.com`.

## Check it works
- Open `https://<your-url>/health` in a browser. It should show `{"ok":true}`.
- `https://<your-url>/v1/chat/completions` without sign-in must answer 401. That means it is protected.

## Point the app at it
- In each user's `.env`, set: `CONSIZ_SERVER_URL=https://<your-url>`
- Users no longer need `OPENROUTER_API_KEY`. Remove it from any shared copy or build.
- Run `python main.py`, sign in with Google, then middle-click some text.

## Good to know (free plan)
- The server sleeps after ~15 min idle. The first answer after a pause takes 30-50 s.
- Daily-limit counts live in a local file and reset when Render restarts the service.
- For real users: upgrade to the paid always-on plan (about $7/month) and add a persistent disk
  or a hosted database for the counts.

## Change limits later
- Render dashboard > conciz-server > Environment: edit `DAILY_LIMIT`, `OPENROUTER_MODEL`,
  `MAX_OUTPUT_TOKENS`, `ALLOWED_EMAILS`. It redeploys by itself.
