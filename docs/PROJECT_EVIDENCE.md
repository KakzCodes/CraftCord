# CraftCord — Project Evidence Record

This file is the source of truth for what has actually been verified,
and when. Nothing here is estimated — a metric that hasn't been measured
is marked `PENDING`, not guessed. See `CV_PROJECT_ENTRY.md` for the
CV-facing summary this record justifies.

## Change history

| Date | Entry |
| --- | --- |
| 2026-10-09 | Record created during Prototype 0 (repository audit and baseline). |
| 2026-10-10 | Prototype 1 started: Windows prerequisites confirmed; added an `on_ready` log line before attempting the first real startup (see below). |

---

## Prototype 0 — Repository audit and baseline

**Date:** 2026-10-09
**Environment this audit ran in:** a sandboxed container with no network
access and no project dependencies installed — Docker, pytest, and every
third-party package used by the code (discord.py, SQLAlchemy, httpx,
etc.) were all unavailable here. Everything below is either static
inspection (reading files, `grep`, `python -m py_compile`) or a fix
applied directly to the source. No dependency install, test run, or
container build was possible in this environment — see "Not yet
verified" below for what Prototype 1 needs to establish on a real
(Windows + Docker Desktop) machine.

### Features present, confirmed by inspection

- `/server` command group: start, stop, restart, status, info, list, ip (7 commands).
- Player-linking commands, ungrouped: link, unlink, whois, online, locate (5 commands).
- `/admin` command group: register-server, create-server, unregister-server, set-default (4 commands).
- Meta commands: help, ping, invite, botinfo (4 commands).
- SQLAlchemy 2.0 async models for 5 tables (guilds, servers, users, audit_log, server_sessions), with one Alembic migration (`0001_initial_schema.py`) creating all of them, including a partial unique index limiting a guild to one default server and a `CHECK` constraint on the guild tier enum.
- A repository layer (one class per table) that never calls `commit()`/`rollback()` itself — confirmed by grep; only `db/session.py`'s context manager does.
- Two Pterodactyl API clients: a client-API client (`ptlc_` key) used by day-to-day commands, and an application-API client (`ptla_` key, optional) used only by `/admin create-server` for on-demand provisioning.
- A composable decorator stack (`@audit`, `@ensure_guild_registered`, `@requires_server`, `@requires_admin`) applied consistently across all 20 commands.
- Dockerfile (multi-stage build), docker-compose.yml (bot + Postgres with a healthcheck), and an entrypoint script that runs `alembic upgrade head` before starting the bot.
- Unit tests for the Pterodactyl client, RCON client, embeds, and repository layer, plus one integration test — present in `tests/`, but see "Not yet verified" below.

### Verified facts (checked directly, this session)

- Every `.py` file in the project compiles cleanly (`python -m py_compile`) — syntax-valid.
- File structure matches the intended layout exactly (confirmed with `find`).
- **20 slash commands implemented**, not 19 — confirmed by an exact `grep` count of `@app_commands.command`/`@group.command` decorators across all four cog files (7 + 5 + 4 + 4 = 20). Earlier documentation (the project brief and `README.md`) said 19, left over from before `/admin create-server` was added; both have been corrected.
- `COMMANDS.md`'s table already had the correct 20 rows — only the prose summary in `README.md` was stale.
- No `Base.metadata.create_all()` calls anywhere in application code — schema is Alembic-only, as required.
- No `print()` calls, no bare `except:`, no `TODO`/`FIXME`/`NotImplementedError` markers anywhere in `src/`.
- Every third-party import actually used in `src/` has a matching pinned dependency in `pyproject.toml`, and every declared dependency is actually used somewhere — no missing or unused top-level dependencies.
- `config.py`'s `Settings` model validates the *format* of Pterodactyl/RCON credentials (URL scheme, `ptlc_`/`ptla_` key prefixes) but never contacts the panel, RCON port, or database at startup — confirmed by reading `config.py` and `bot.py`'s `setup_hook`. This means placeholder-but-valid-looking values are enough to get the bot through startup without a real Pterodactyl panel.

### Defects found and fixed during this audit

1. **Command-count documentation error.** The project brief and `README.md` both said "19 commands implemented," which was true before `/admin create-server` was added but not after (true count: 20). Fixed in both documents.
2. **Secret-redaction gap.** `logging_config.py`'s `_SECRET_KEYS` set — the structlog processor that redacts secret values before they reach a log line — did not include `pterodactyl_application_api_key` (the new application-API key setting added alongside on-demand server creation). Checked by grep that this field is never actually passed to a logger call anywhere today, so nothing has leaked in practice, but the redaction safety net had a real gap for it. Fixed by adding it to the set.

### Not yet verified (requires execution — Prototype 1 onward, on a machine with Docker and internet access)

- Whether `pip install -e ".[dev]"` succeeds with no dependency conflicts.
- `pytest` results: pass/fail/skip counts and measured coverage percentage. **Status: PENDING — no test has ever been run.**
- Whether `docker compose up --build` succeeds, Alembic migrations apply cleanly against a real Postgres container, and the bot connects to Discord's gateway.
- Whether any slash command actually executes correctly against Discord's real API.
- Whether the composable decorator stack behaves as designed once discord.py actually builds a real command tree from it — this was reasoned through carefully (see the project brief's Section 2a) but never exercised against the real library.
- Ruff lint results.
- Anything involving a real Pterodactyl panel or Minecraft server (not available yet) — power actions, resource stats, on-demand server creation, RCON player lookups.

### Known architectural limitations (by design, not defects)

- RCON connection details are one global configuration, not per-server (the schema has no per-server RCON columns) — acceptable under the current one-server-per-guild limit, a known gap for future multi-server guilds.
- `@requires_admin`'s "configured bot-admin role" checks a hardcoded role name (`"CraftCord Admin"`) — there's no per-guild admin-role setting yet.
- `/locate`'s "Copy" button posts coordinates as ephemeral plain text, since bots have no real OS-clipboard API to call.
- The server-embed thumbnail is a placeholder image URL.

### Milestone plan

No change to the brief's Prototype 1–7 roadmap is indicated by this audit — proceed to **Prototype 1 (local application startup)** next, on the Windows machine where Docker Desktop and internet access are available.

---

## Prototype 1 — Local application startup (in progress)

**Date started:** 2026-10-10

**Windows prerequisites — confirmed present, no installs needed:**

| Tool | Reported version |
| --- | --- |
| Docker | 29.8.1 (build 4a63305) |
| Docker Compose | v5.5.1 |
| Python | 3.12.10 |
| Git | 2.56.0.windows.2 |

**Fix applied before the first real startup attempt:** `bot.py` had no
`on_ready` handler. `setup_hook`'s `slash_commands_synced` log line only
proves the REST call to register commands succeeded — it runs before the
gateway connection is confirmed, so on its own it isn't evidence the bot
is actually online. Added an `on_ready` handler that logs a `bot_ready`
line (bot user tag, id, guild count) once the gateway connection is live,
since this milestone's whole point is confirming that connection
actually happens. Found during inspection while preparing this
milestone's verification steps, before any startup attempt — not found
by running the code, since it still can't be run in the audit
environment.

**Second fix, found reviewing the user's actual filled-in `.env` before the first run:** every optional
setting left blank per `.env.example`'s own "leave this line blank to disable" instruction
(`PTERODACTYL_APPLICATION_API_KEY=`, `PTERODACTYL_OWNER_USER_ID=`, `PTERODACTYL_EGG_ID=`,
`PTERODACTYL_DEPLOY_LOCATION_IDS=`, and potentially `DISCORD_GUILD_ID_DEV=`) would have been read by
pydantic-settings as the literal empty string `""`, not `None` — which fails the `ptla_` prefix check or
int parsing immediately, crashing `Settings()` at the very first line of startup. `.env.example` documented
a pattern the code didn't actually support. Fixed with a `mode="before"` validator in `config.py` that
converts a blank string to `None` for every optional setting before type coercion runs. Found by reviewing
the user's real `.env` contents, not by running it — same category of defect as Prototype 0's command-count
error: documentation (here, `.env.example`'s own instructions) describing behaviour the code didn't match.

**Also flagged (not a code issue): the user pasted a real Discord bot token into chat while sharing their
`.env`.** Treated as compromised; the user was told to reset it via the Developer Portal immediately and
never paste a real secret into chat again. No token value is recorded in this file or anywhere in the repo.

**Startup attempt 1:** `docker compose up --build`, run by the user on Windows. Postgres image pulled fine; the
`bot` image build failed during `pip install .` with `OSError: Readme file does not exist: README.md`.
Cause: `pyproject.toml` declares `readme = "README.md"`, but the Dockerfile's builder stage only copied
`pyproject.toml` and `src/` before running `pip install`, so hatchling couldn't find the README it needed
for package metadata. First real execution of this project, and it immediately caught a real bug no amount
of `py_compile` could have found. Fixed by also copying `README.md` in that `COPY` step.

**Startup attempt 2:** `PENDING` — fix not yet re-run.

**Startup attempt 3:** Build succeeded, Postgres became healthy, Alembic migration `0001` applied
successfully against a real Postgres container, and Discord login succeeded (token valid). Crashed in
`setup_hook` at `tree.sync(guild=...)` with `discord.errors.Forbidden: 403 Forbidden (error code: 50001):
Missing Access`. Not a code defect — the bot was invited to the test guild without the
`applications.commands` OAuth2 scope, so it has no permission to register slash commands there. User
re-invited with the correct scope; next attempt pending.

**Startup attempt 4: SUCCESS.** Full stack came up correctly: Postgres container healthy, Alembic
migration already applied from the previous attempt (confirmed idempotent — no error re-running against an
already-migrated database), bot authenticated with Discord, slash commands synced (`count: 11` — the
correct number of *top-level* registrations: 9 standalone commands + 2 groups, `/server` and `/admin`,
whose sub-commands register inside that single group entry rather than counting separately; all 20
commands are present), and `bot_ready` fired with the live bot user tag and guild count. This is the first
time any part of this project has been confirmed working by actually running it, rather than by
inspection.

**Confirmed by the user, in their live test server:**
- `/ping` and `/help` both respond correctly.
- `Ctrl+C` produces a clean shutdown — `Gracefully Stopping...`, both containers stop with no error or traceback.

**Prototype 1 — Local application startup: COMPLETE.** Every item in the brief's checklist for this
milestone is now verified by actually running it, not just by inspection: container build, Postgres health,
Alembic migrations (including a confirmed-idempotent second run), Discord authentication, slash-command
registration, at least two commands responding correctly in a live Discord server, and a clean shutdown.

**Next milestone:** Prototype 2 — database and persistence (verify constraints, cascades, and data survival
across a normal container restart, beyond what Prototype 0's static inspection already confirmed about the
schema).

---

## Prototype 2 — Database and persistence (in progress)

**Date started:** 2026-10-10

**Confirmed by the user, against the real running stack:**
- `guilds` table correctly holds the guild's real Discord snowflake id, name, and default `tier='grass'` — proves `GuildRepository.upsert()` (and the `@ensure_guild_registered` decorator that calls it) works end-to-end.
- `audit_log` shows real rows for `link`, `unlink`, `whois` (×2), `help` (×2), `ping` (×2), all `success=true` with real `duration_ms` values — proves the `@audit` decorator correctly wraps commands and writes rows for every invocation, against a real database.
- Data survived a full `docker compose down` + `docker compose up -d` (container recreation, not just a restart) — `/whois` still remembered the linked account afterward. Proves the named Docker volume (`pgdata`) is correctly persisting Postgres data independent of the container's lifecycle.
- This also indirectly confirms the composable decorator stack (`@audit` / `@ensure_guild_registered` / `@requires_server`) — previously flagged as "reasoned through but never tested against a real discord.py tree" — genuinely works: `/link` (a command with a real string option) and `/whois` (optional user option) both executed correctly.

**Uniqueness constraint confirmed:** attempting to insert a second user with an already-claimed
`minecraft_username` ("notch") correctly failed with `duplicate key value violates unique constraint
"uq_users_minecraft_username"` — the database rejects it exactly as designed, confirming the schema's
case-insensitive username uniqueness actually works, not just that the migration ran.

**Server registration, session history, and cascade-delete behaviour remain untested** — all three need
either a real Pterodactyl panel (not available yet, Prototype 7) or direct SQL poking that doesn't add much
beyond what the uniqueness test already demonstrated. Deferred rather than forced.

**Error-handling confirmed working end-to-end:** running `/online` with no server registered produced a
clean, user-friendly ephemeral error ("No matching server is registered for this guild. An admin can
register one with `/admin register-server`.") rather than a crash — proves the
`@requires_server` → `ServerNotRegistered` → `@audit`'s error-to-embed conversion chain all actually work
together against the real bot, not just in isolated unit tests.
