# CraftCord

CraftCord is a Discord bot that lets a community start, stop, restart, and
monitor Minecraft servers hosted on a [Pterodactyl](https://pterodactyl.io/)
panel, directly from Discord slash commands. **Iteration 1 (this release)**
covers the free-tier MVP: server power control, live status, player
lookup/location via RCON, and Minecraft-account linking, all backed by
PostgreSQL as the single source of truth. There is no web dashboard, no
paid-tier behavior, no chat bridge, and no scheduled backups yet — see
[Roadmap](#roadmap).

> **Command count note:** this iteration's spec both targeted "~15
> commands" and individually enumerated 19 (later 20, once `/admin
> create-server` was added as an approved extension). Every individually
> enumerated command is implemented (see [COMMANDS.md](COMMANDS.md))
> rather than guessing which ones to cut.

## Architecture

```
                    ┌──────────────┐
   Discord slash  →  │  CraftCord   │  ─── HTTP (client API) ──→  Pterodactyl Panel
   commands         │     Bot      │                                    │
                    │  (discord.py)│                                    │ controls
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
- **Bot → PostgreSQL:** every piece of persistent state (registered guilds
  and servers, linked Minecraft accounts, the audit log, and uptime session
  history) lives in Postgres, owned entirely by Alembic migrations.
- **Bot → RCON:** live player lists and coordinate lookups talk directly to
  the Minecraft server's RCON interface.

## Prerequisites

- A running [Pterodactyl](https://pterodactyl.io/) panel, with at least one
  Minecraft server already created on it.
- A Pterodactyl **client** API key (Panel → Account Settings → API
  Credentials) — not an application/admin key. It should start with `ptlc_`.
- A [Discord application](https://discord.com/developers/applications) with
  a bot user and its token, invited with the `bot` and
  `applications.commands` scopes (see [below](#inviting-the-bot)).
- Docker and Docker Compose.

## Setup

```bash
git clone <this-repo-url> craftcord
cd craftcord
cp .env.example .env
# edit .env and fill in DISCORD_TOKEN, PTERODACTYL_URL, PTERODACTYL_API_KEY,
# DATABASE_URL / POSTGRES_USER / POSTGRES_PASSWORD, and RCON_HOST / RCON_PORT / RCON_PASSWORD
docker compose up --build
```

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

> _Placeholders — add real screenshots here before publishing._

| Command           | Screenshot                          |
| ----------------- | ------------------------------------ |
| `/help`           | ![help](docs/screenshots/help.png)   |
| `/server start`   | ![server start](docs/screenshots/server-start.png) |
| `/server status`  | ![server status](docs/screenshots/server-status.png) |
| `/online`         | ![online](docs/screenshots/online.png) |
| `/locate`         | ![locate](docs/screenshots/locate.png) |

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

```bash
pip install -e ".[dev]"
pytest
```

Coverage is enforced at ≥70% on `src/craftcord` (see `[tool.coverage.report]`
in `pyproject.toml`); run `pytest --cov` or `coverage run -m pytest && coverage report`
to check locally.

### Adding a migration

Schema changes always go through Alembic — the application never calls
`Base.metadata.create_all()`. After changing `src/craftcord/db/models.py`:

```bash
# from inside the bot container, or locally with DATABASE_URL pointed at a
# real Postgres instance and the rest of .env's required vars set:
alembic revision --autogenerate -m "describe the change"
# review the generated file in alembic/versions/ before committing —
# autogenerate is a starting point, not a guarantee
alembic upgrade head
```
