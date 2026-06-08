# Deploying the Võro MCP server to Modal

This hosts the server in Modal's cloud so Claude and ChatGPT (the web apps) can
reach it over HTTPS. You run a few commands from your laptop once. After that the
server lives in Modal and wakes on demand (idle = no cost).

Claude and ChatGPT cannot send API keys or custom headers to a custom connector.
They only support OAuth or "no auth". So we run a no-auth server behind a random
secret URL path (`/<random>/mcp`). That secret URL is effectively your password,
so never commit or share it.

---

## Scripted setup

Prerequisites:

- A free Modal account: https://modal.com
- Python and `make` on your laptop.
- Modal CLI authenticated once:

```sh
python -m pip install modal
modal token new        # opens a browser to link your Modal account
```

One command from the repo root:

```sh
make deploy
```

The script creates or updates the Modal secret, creates the `vro-data` Volume,
hydrates the Volume from GitHub release assets if data is missing, and then runs
`modal deploy modal_app.py`. When Modal prints the web function URL, the script
also prints the full MCP endpoint by appending your secret `MCP_PATH`.

For the secret path, the script uses `MCP_PATH` from your environment if set,
otherwise from a local `.env` file. If neither has it, the script generates a
fresh random path and saves it to `.env` (mode `600`). `.env` is gitignored
because the path is effectively the hosted server's password.

If you would rather choose the secret path yourself instead of a generated one,
set `MCP_PATH` in `.env` to the value you want (e.g. `/my-secret-path/mcp`) and
run `make deploy-local-secret`. That pushes exactly the `MCP_PATH` from `.env`
to Modal and fails fast if it is empty, so it never falls back to a random path.

Copy `.env.example` to `.env` if you want persistent deploy defaults. Shell
environment variables still override `.env`.

Common deploy commands:

```sh
make deploy                         # deploy with the secret + settings from .env
make deploy-new-secret              # generate a fresh secret URL, save to .env, deploy
make deploy-local-secret            # push the MCP_PATH you set in .env, then deploy
make deploy-release                 # deploy with GitHub releases as the data source
make deploy-release-force           # overwrite Modal data from GitHub releases
make deploy-local                   # upload from this repo's ./data
make deploy-local DATA_DIR=/path    # upload from another local data directory
make deploy-local-force             # overwrite Modal data from local files
make deploy-none                    # code-only deploy, never touch data
```

To remove the hosted server and all uploaded Modal data:

```sh
make undeploy
```

That stops the Modal app, deletes the `vro-data` Volume, and deletes the
`vro-mcp-secret` secret.

---

## Manual setup

### 1. Create the secret URL path
Generate a random segment and store it as a Modal secret. The server reads
`MCP_PATH` from it.

```sh
# Generate a random path (copy the output):
python -c "import secrets; print('/'+secrets.token_urlsafe(24)+'/mcp')"
# e.g. ->  /Xb9...big-random.../mcp

# Store it (paste YOUR value):
modal secret create vro-mcp-secret MCP_PATH="/Xb9...big-random.../mcp"
```

### 2. Upload the big data to a Modal Volume
The SQLite DBs and Giella models do NOT go in git or the image. They live here.
If you have not downloaded them locally yet, run this first from the repo root:

```sh
scripts/fetch_data.sh
scripts/fetch_giella.sh
```

Then upload them:

```sh
# Create the volume:
modal volume create vro-data

# Upload the three databases (note the renamed targets):
modal volume put vro-data data/vro_dictionary.sqlite /dictionary.sqlite
modal volume put vro-data data/vro_corpus.sqlite     /corpus.sqlite
modal volume put vro-data data/vro_word_bag.sqlite   /word_bag.sqlite

# Upload the Giella FST models if present:
modal volume put vro-data data/giella-share /giella-share
```

### 3. Deploy
```sh
modal deploy modal_app.py
```

Modal builds the image (installs the Divvun binaries) and prints a URL like:

```
https://<your-workspace>--vro-mcp-serve.modal.run
```

Your full MCP endpoint is that URL **+ your secret path**:

```
https://<your-workspace>--vro-mcp-serve.modal.run/Xb9...big-random.../mcp
```

Keep this full URL secret.

---

## Connect the clients

Use the full MCP endpoint printed by `make deploy`, for example:

```text
https://<workspace>--vro-mcp-serve.modal.run/<secret>/mcp
```

### Claude Code

```sh
claude mcp add --transport http --scope user vro "https://<workspace>--vro-mcp-serve.modal.run/<secret>/mcp"
```

### Codex CLI

```sh
codex mcp add vro --url "https://<workspace>--vro-mcp-serve.modal.run/<secret>/mcp"
```

### Claude web  (Pro/Max/Team/Enterprise)
Settings → Connectors → Add custom connector → paste the full secret URL → leave
Advanced/OAuth empty → Add. Then enable the `vro` tools in a chat.

### ChatGPT  (Plus/Pro, Developer Mode)
Enable Developer Mode first (Settings → Apps → Advanced), then: Settings → Apps →
Create app → paste the full secret URL → Authentication: "No authentication" →
tick "I understand and wish to continue" → Create.

---

## Verify the deploy

Quick checks that the endpoint is live and the secret path is doing its job:

```sh
# Should return JSON / an event stream (NOT 404) at the secret path:
curl -i https://<workspace>--vro-mcp-serve.modal.run/<secret>/mcp

# Any other path should 404 (that's the point):
curl -i https://<workspace>--vro-mcp-serve.modal.run/mcp

# Live logs while you test from Claude/ChatGPT:
modal app logs vro-mcp
```

If the Giella tools report "unavailable", run `check_setup` from the client and
check `modal app logs vro-mcp`.

---

## Updating later
`scripts/deploy_modal.sh` touches data only when the volume is missing it, so
routine redeploys are fast:
- **Code change:** `make deploy` (skips data automatically when already present).
- **Local data change:** `make deploy-local-force` or
  `make deploy-local-force DATA_DIR=/path/to/data`.
- **Code-only, never touch data:** `make deploy-none`.
- **Rotate the secret URL:** `make deploy-new-secret`, then update the URL in
  both clients.
- **Use your own secret URL:** set `MCP_PATH` in `.env`, then
  `make deploy-local-secret` and update the URL in both clients.
