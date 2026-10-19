# CraftCord

CraftCord is a Discord bot that lets a community start, stop, restart, and
monitor Minecraft servers hosted on a [Pterodactyl](https://pterodactyl.io/)
panel, directly from Discord slash commands. **Iteration 1 (this release)**
covers the free-tier MVP: server power control, live status, player
lookup/location via RCON, and Minecraft-account linking, all backed by
PostgreSQL as the single source of truth. There is no web dashboard, no
paid-tier behavior, no chat bridge, and no scheduled backups yet — see
[Roadmap](#roadmap).

> **Implemented command count: 20** — 7 `/server`, 5 player, 4 `/admin`,
> and 4 meta commands. The source brief's figure of 19 conflicts with its own
> list; the registered cog inventory is checked by a unit test. See
> [COMMANDS.md](COMMANDS.md).

## Architecture

```
                    ┌──────────────┐
   Discord slash  →  │  CraftCord   │  ── HTTP client API ─────→  Pterodactyl Panel
   commands         │     Bot      │                                    │
                    │  (discord.py)│  ── HTTP application API ─→  (optional provisioning)
                    └──────┬───────┘                                    ▼
                           │                                   Minecraft Container
                 ┌─────────┼─────────┐                                  │
                 │                   │                                  │
          asyncpg│                   │RCON (mcrcon,                    │
                 ▼                   ▼  via asyncio.to_thread)  ◄───────┘
          ┌─────────────┐    ┌───────────────┐
          │ PostgreSQL  │    │ Minecraft RCON │
          │ (source of  │    │   interface    │
          │   truth)    │    └───────────────┘
          └─────────────┘
```

- **Discord → Bot:** slash commands only (no prefix commands), routed through
  cogs in `src/craftcord/cogs/`.
- **Bot → Pterodactyl:** power actions (start/stop/restart), live resource
  stats, and connect-address lookups go through `core/pterodactyl.py`.
  The optional Application API client provisions servers from one fixed
  admin-configured template; it is used only by `/admin create-server`.
- **Bot → PostgreSQL:** every piece of persistent state (registered guilds
  and servers, linked Minecraft accounts, the audit log, and uptime session
  history) lives in Postgres, owned entirely by Alembic migrations.
- **Bot → RCON:** live player lists and coordinate lookups talk directly to
  the Minecraft server's RCON interface.

## Prerequisites

- Python 3.12 and Docker with Docker Compose for development and automated
  tests. The PostgreSQL integration tests start a disposable database
  container.
- A [Discord application](https://discord.com/developers/applications) and bot
  token to run the bot. Invite it with the `bot` and `applications.commands`
  scopes (see [below](#inviting-the-bot)).
- A running [Pterodactyl](https://pterodactyl.io/) panel, a Minecraft server,
  and a Pterodactyl **client** API key (starts with `ptlc_`) to use live server
  controls. They are not needed for mocked tests or to build the image.
- A Pterodactyl **application** API key (`ptla_`) and a configured creation
  template only if you want to use `/admin create-server`.

## Setup

```powershell
# Run these commands from the repository root.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
docker compose config --quiet
docker compose up --build
```

In `.env`, set a real `DISCORD_TOKEN`, a syntactically valid `PTERODACTYL_URL`
and client key, and RCON values. Never commit `.env`. The example's panel and
RCON values are placeholders: they pass configuration validation but cannot
call a real panel or Minecraft server. Those services are not needed for the
bot to connect to Discord.

`DATABASE_URL` uses the Compose service name `db` because the bot connects
inside the Compose network; `localhost` inside the bot container would refer
to the bot itself. From Windows, `db` is not a host name, and the database
port is not published by default. `RCON_HOST` must resolve and be reachable
from inside the bot container (for example, another container on the same
Compose network or a reachable external host).

On startup the `bot` container runs `alembic upgrade head` against the `db`
service before starting the bot process (see `scripts/entrypoint.sh`) — there's
nothing to migrate manually.

## Inviting the bot

1. Once `/botinfo` or the console logs confirm the bot is online, run
   `/invite` in any server it's already in, **or** build the URL yourself from
   the Developer Portal with the `bot` and `applications.commands` scopes.
2. Invite it to your server.
3. Register your first server, one of two ways (both need `Manage Server`
   or the configured bot-admin role):
   - **Already have a server on the panel?** Run `/admin register-server`
     with its Pterodactyl UUID and numeric ID. CraftCord validates the UUID
     against the panel before saving it.
   - **Want CraftCord to provision one for you?** Set up the creation
     template in `.env` (see the "Pterodactyl (application API)" section of
     `.env.example`), then run `/admin create-server <name>`. This is
     admin-only for now; self-service server creation for individual users
     is a paid-tier feature planned for a later iteration (see
     [Roadmap](#roadmap)).
4. Run `/help` to see everything else CraftCord can do.

## Screenshots

Screenshots of live command responses are not included yet. Add them under
`docs/screenshots/` after verifying the corresponding command in a test server;
live Pterodactyl and RCON screenshots require those services.

## Roadmap

Iteration 1 deliberately stops short of the following — they're the
intended direction for Iteration 2, not a promise of scope or timeline:

- Web dashboard
- Tier-gated paid features (iron / gold / diamond behavior — the `tier`
  column already exists on `guilds`, but only free-tier/"grass" behavior is
  implemented today)
- Self-service server creation for individual (paid-tier) users, each
  getting their own server, with admins controlling who's eligible —
  `/admin create-server` today is admin-only and provisions on the guild's
  behalf, not a given member's
- Per-guild or per-user configurable creation templates (today there's one
  fixed template, set once in `.env`, shared by every guild)
- In-game ↔ Discord chat bridge
- Server version control / backups
- Scheduled automatic backups

## Development

### Running tests

Tests need Docker available locally (for the `testcontainers`-managed
Postgres instance used by the repository and integration tests):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Coverage is enforced at ≥70% on `src/craftcord` (see `[tool.coverage.report]`
in `pyproject.toml`). Run these PowerShell commands for the full checks:

```powershell
.\.venv\Scripts\python.exe -m coverage run -m pytest
.\.venv\Scripts\python.exe -m coverage report --fail-under=70
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pip-audit.exe
```

Repository integration tests need Docker Desktop running because they start a
disposable PostgreSQL container. Pterodactyl and Mojang HTTP calls are mocked
in automated tests; no automated test proves access to a real panel or game
server.

### Adding a migration

Schema changes always go through Alembic — the application never calls
`Base.metadata.create_all()`. After changing `src/craftcord/db/models.py`:

```powershell
docker compose exec bot alembic revision --autogenerate -m "describe the change"
# Review the generated migration in alembic/versions/ before applying it.
docker compose exec bot alembic upgrade head

## Licence

CraftCord is distributed under the MIT License; see [LICENSE](LICENSE).
```
