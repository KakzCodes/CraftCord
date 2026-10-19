# CraftCord

CraftCord is a Discord bot that lets a community start, stop, restart, and
monitor Minecraft servers hosted on a [Pterodactyl](https://pterodactyl.io/)
panel, directly from Discord slash commands. **Iteration 1 (this release)**
covers the free-tier MVP: server power control, live status, player
lookup/location via RCON, and Minecraft-account linking, all backed by
PostgreSQL as the single source of truth. There is no web dashboard, no
paid-tier behavior, no chat bridge, and no scheduled backups yet — see
[Roadmap](#roadmap).

> **Command count:** the agreed command inventory enumerates 20 commands:
> 7 `/server`, 5 player, 4 `/admin`, and 4 meta commands. The prose elsewhere
> calls the set 19, but that does not match the enumerated list. CraftCord
> implements all 20 listed commands; see [COMMANDS.md](COMMANDS.md).

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

- A running [Pterodactyl](https://pterodactyl.io/) panel, with at least one
  Minecraft server already created on it.
- A Pterodactyl **client** API key (Panel → Account Settings → API
  Credentials) — not an application/admin key. It should start with `ptlc_`.
- A [Discord application](https://discord.com/developers/applications) with
  a bot user and its token, invited with the `bot` and
  `applications.commands` scopes (see [below](#inviting-the-bot)).
- Docker and Docker Compose.

## Setup

```powershell
git clone https://github.com/KakzCodes/craftcord.git
Set-Location craftcord
Copy-Item .env.example .env
notepad .env
docker compose up --build
```

In `.env`, set `DISCORD_TOKEN`, a syntactically valid `PTERODACTYL_URL` and
client key, and RCON values. `DATABASE_URL` must use the Compose service name
`db` (as in the example), because the bot connects from inside its container;
`localhost` there would refer to the bot container itself. `RCON_HOST` must
also be reachable from that container. A real panel or Minecraft server is
needed to verify those integrations, but not to validate configuration.

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

```powershell
py -m pip install -e ".[dev]"
py -m pytest
```

Coverage is enforced at ≥70% on `src/craftcord` (see `[tool.coverage.report]`
in `pyproject.toml`); run `py -m coverage run -m pytest` followed by
`py -m coverage report` to check locally. Repository integration tests need
Docker Desktop running because they start a disposable PostgreSQL container.

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
