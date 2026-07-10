# Setup Guide — LinkedIn + X/Twitter API access

This guide walks you through creating the developer apps and obtaining the
credentials `comet_repurposer` needs to publish automatically.

Total time: ~1 hour (LinkedIn) + ~30 min (X).

---

## Part 1 — LinkedIn (Marketing API)

### Step 1: Create the app

1. Go to <https://www.linkedin.com/developers/apps/new>
2. Sign in with the LinkedIn account that will own the posts.
3. Fill the form:
   - **App name**: `comet_riobamba_publisher`
   - **LinkedIn Page**: select your personal page (or create one if you don't have it)
   - **Privacy policy URL**: any public URL (you can use your LinkedIn profile URL)
   - **App logo**: upload any image (placeholder is fine for dev)
   - **Legal agreement**: check the box
4. Click **Create app**.

### Step 2: Add the Marketing API product

1. In the app dashboard, scroll to **Products**.
2. Find **Marketing API** and click **Select**.
3. This grants the `w_member_social` scope — required to post on behalf of
   the user.

### Step 3: Configure OAuth 2.0

1. In the left sidebar, click **Auth**.
2. Under **OAuth 2.0 settings**:
   - **Authorized redirect URLs for your apps**: add
     ```
     http://localhost:8080/callback
     ```
3. Under **Client credentials** (top of the page):
   - Copy **Client ID** → put it in `.env` as `LINKEDIN_CLIENT_ID`
   - Copy **Client Secret** → put it in `.env` as `LINKEDIN_CLIENT_SECRET`

### Step 4: Run the OAuth flow

From your project root:

```powershell
cd C:\comet-riobamba-v31
python -m comet_repurposer auth-linkedin
```

This will:
1. Open your browser
2. Ask you to log in to LinkedIn and authorize the app
3. Redirect to `http://localhost:8080/callback`
4. Print the access token, refresh token, and person_id to the console

Copy those values into your `.env`:

```
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_ACCESS_TOKEN_EXPIRES_AT=...
LINKEDIN_REFRESH_TOKEN=...
LINKEDIN_REFRESH_TOKEN_EXPIRES_AT=...
LINKEDIN_PERSON_ID=...
```

### Step 5 (optional): Verify with a test post

```powershell
# Generate a draft and enqueue it
python -m comet_repurposer generate --source latest --limit 1 --enqueue-linkedin

# Approve it
python -m comet_repurposer queue                  # see the job ID
python -m comet_repurposer approve <job_id>

# Dry-run (no real post)
python -m comet_repurposer publish --dry-run

# Real post
python -m comet_repurposer publish --for-real --i-know
```

### Token renewal

- `access_token` lasts 60 days. `comet_repurposer` auto-refreshes it
  using the `refresh_token` when expiry is within 5 days.
- `refresh_token` lasts 365 days. After that, re-run
  `auth-linkedin` to get a new pair.

---

## Part 2 — X / Twitter Developer

### Step 1: Create the developer account

1. Go to <https://developer.x.com/en/portal/dashboard>
2. Sign in with the X account that will own the posts.
3. Fill the sign-up form:
   - **Choose an API plan**: Free (1,500 posts/month, 50 posts/24h)
     is enough for MVP. If you need more, Basic is $100/month.
   - **Describe your use case**: 200+ chars. Be honest:
     "Autonomous AI research agent that produces technical content
     about agent engineering. The agent posts to Moltbook (a developer
     social network). I want to cross-post highlights to X/Twitter."

### Step 2: Create a Project + App

1. In the dashboard, click **+ Create Project**.
   - Name it `comet_riobamba`
2. Choose **App environment**: `Development`
3. Name your app (must be globally unique): `comet_riobamba_poster`
4. Copy the **API Key** and **API Key Secret** that appear:
   ```
   TWITTER_API_KEY=...
   TWITTER_API_KEY_SECRET=...
   ```

### Step 3: Set App permissions to Read and Write

1. In the app's **Settings** tab, scroll to **App permissions**.
2. Change from "Read" to **Read and Write**.
3. Save.

### Step 4: Generate Access Token + Secret

1. In the **Keys and tokens** tab, scroll to **Authentication Tokens**.
2. Click **Generate** under **Access Token and Secret**.
3. Copy both values:
   ```
   TWITTER_ACCESS_TOKEN=...
   TWITTER_ACCESS_TOKEN_SECRET=...
   ```

### Step 5: Generate Bearer Token (optional)

Only needed if you want to use read endpoints (look up user info, fetch
tweet metrics). For pure posting, you don't need this.

1. In the same **Keys and tokens** tab, scroll to **Bearer Token**.
2. Click **Generate**.
3. Copy:
   ```
   TWITTER_BEARER_TOKEN=...
   ```

### Step 6: Verify with a test tweet

```powershell
# Generate a draft and enqueue it
python -m comet_repurposer generate --source latest --limit 1 --enqueue-x

# Approve it
python -m comet_repurposer queue
python -m comet_repurposer approve <job_id>

# Dry-run
python -m comet_repurposer publish --dry-run

# Real post
python -m comet_repurposer publish --for-real --i-know
```

---

## Common pitfalls

### LinkedIn

- **"unauthorized_scope_error"**: your app doesn't have the Marketing API
  product added. Go back to step 2.
- **"invalid_redirect_uri"**: the redirect URI in your app doesn't match
  `http://localhost:8080/callback` exactly (no trailing slash, https vs http).
- **Token expired error after 60 days**: the auto-refresh should handle this,
  but if `refresh_token` itself has expired (>365 days), re-run
  `auth-linkedin`.

### X/Twitter

- **401 Unauthorized**: usually means your App permissions are still "Read".
  Change to "Read and Write" (Step 3) and regenerate the Access Token.
- **403 Forbidden with "Forbidden access"**: Free tier only allows
  `oauth1_user`-context posting. Make sure you're using the user-context
  tokens (`TWITTER_ACCESS_TOKEN` + secret), not just the bearer token.
- **429 Too Many Requests**: you hit the 50 posts/24h limit. Wait or
  upgrade to Basic tier.

### Both platforms

- **Kill switch active**: delete `data/KILL_SWITCH` or run
  `python -m comet_repurposer unkill`.
- **"Refusing to publish for real without --i-know"**: this is the safety
  belt. Re-run with `--for-real --i-know`.

---

## After first successful test

Once you've confirmed both platforms work, schedule a daily run:

```powershell
# Windows Task Scheduler — run daily at 09:00
python -m comet_repurposer generate --source latest --limit 3 \
    --enqueue-linkedin --enqueue-x
python -m comet_repurposer approve --all
python -m comet_repurposer publish --for-real --i-know
```

Or, more conservatively, approve manually each day so you keep the 1-click
gate:

```powershell
# Daily generation (automated)
python -m comet_repurposer generate --source latest --limit 3 \
    --enqueue-linkedin --enqueue-x

# Manual review + approval
python -m comet_repurposer queue
python -m comet_repurposer approve <job_id_1> <job_id_3>   # only the good ones

# Automated publishing of approved jobs (could be a separate scheduled task)
python -m comet_repurposer publish --for-real --i-know
```
