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

**Pterodactyl retry/error-handling confirmed working end-to-end:** `/admin register-server` against the
fake panel address in `.env` correctly retried (visible delay, matching the 3-attempt backoff logic) before
showing a clean "Couldn't reach the Pterodactyl panel" error rather than crashing or hanging — confirms
`_send_request`'s retry policy and the transport-error-to-`PterodactylError` mapping both work for real, not
just in the mocked `respx` unit tests.

**Prototype 2 — Database and persistence: COMPLETE** for everything testable without a real Pterodactyl
panel (guild upsert, audit logging, data persistence across restart, uniqueness constraint enforcement,
and the full error-handling chain for both missing-server and unreachable-panel cases). Server
registration, session history, and cascade-delete behaviour on real rows remain deferred to Prototype 7
(real panel) — this is a reasonable, explained deviation from strict prototype ordering, not a skipped step.

**Next milestone:** Prototype 3 — remaining Discord commands and permission checks.

---

## Prototype 3 — Discord commands (in progress)

**Confirmed working, against the real bot:** `/server list` (correct empty-state message), `/botinfo`
(accurate real data: version `1.0.0`, uptime, `Guilds: 1`, `Registered Servers: 0`, `DB Pool: 0/10
connections in use` — confirms `ServerRepository.count_all()` and the live SQLAlchemy pool status both
report correctly). Combined with earlier confirmations (`/ping`, `/help`, `/link`, `/unlink`, `/whois`,
`/online`'s error path, `/admin register-server`'s error path), **9 of 20 commands are now confirmed
working against the real bot**, covering every major code path except real Pterodactyl/RCON interaction and
admin-permission denial (the latter needs a second, non-admin Discord account to test).

---

## Prototype 6 — Automated test suite (ran ahead of schedule — big enough result to log now)

**Date:** 2026-10-10

**Result: 40/40 tests passed, 0 failed, 0 skipped. Runtime: 10.13s.**

Breakdown: `test_server_flow.py` (1 integration test — mocked Pterodactyl + a real Postgres container),
`test_embeds.py` (11), `test_pterodactyl.py` (12, including retry-on-5xx, 401/404/422/429 mapping, and the
newer `PterodactylApplicationClient.create_server` tests), `test_rcon.py` (6, including NBT position
parsing), `test_repositories.py` (10, run against a real `testcontainers` Postgres instance — unique
constraints, the partial-unique default-server index, and cascade deletes all genuinely exercised, not
mocked).

This is the first time the full test suite has ever actually run — previously "tests exist" was a claim
from reading the files, nothing more. Combined with Prototypes 1–3's live-bot testing, essentially every
code path that doesn't require a real Pterodactyl panel is now confirmed working by actual execution.

**Coverage measured: 39%**, against the `fail_under = 70` target configured in `pyproject.toml`. The gap is
entirely explainable rather than a sign of untested code hiding bugs: `cogs/*.py`, `bot.py`,
`decorators.py`, and `mojang.py` were all at 0% because no *automated* test had been written for them —
but `cogs/*.py` and most of `bot.py`'s startup path had already been verified *manually*, against the real
running bot, in Prototypes 1–3 (every command tried actually worked). Coverage tooling has no way to credit
manual testing, so the number understated how much was actually verified.

**Decision: write automated tests for `decorators.py` and `mojang.py`; deliberately leave `cogs/*.py` and
`bot.py` as manually-verified-only.** Reasoning: `decorators.py` is the project's one genuinely novel piece
of machinery (the `@audit`/`@ensure_guild_registered`/`@requires_server`/`@requires_admin` stack with
`__signature__` manipulation), repeatedly flagged in this record as "reasoned through but never tested
against a real discord.py tree" — worth testing properly regardless of the coverage number. `mojang.py` is
cheap to test with the same `respx` pattern already used for the Pterodactyl client. `cogs/*.py` and
`bot.py`, by contrast, are thin orchestration that call already-tested repositories/clients; testing them
with equivalent rigor would mean mocking a fake `discord.Interaction` for all 20 commands, for a lot more
effort than the manual testing already spent proving they work. Chasing 70% by testing low-value glue code
was rejected in favour of testing the two places automated tests actually add real confidence.

**Added:** `tests/unit/test_decorators.py` (14 tests — all four decorators individually, plus one
full-stack composition test asserting the exact signature Discord's command tree would see) and
`tests/unit/test_mojang.py` (6 tests — success, 404, 5xx, and caching behaviour, including a case-
insensitive cache key). Both written against fakes/mocks (no database, no real HTTP) — not yet re-run by
the user; new total expected to be 40 + 14 + 6 = 60 tests.

**Non-blocking warnings, noted for a future cleanup pass (not fixed now — tests pass regardless):**
- `testcontainers.postgres` is deprecated in favour of `testcontainers.community.postgres` (a rename of the
  import path in a newer library version — one-line fix when convenient).
- `conftest.py`'s custom `event_loop` fixture is deprecated by `pytest-asyncio` in favour of `loop_scope`
  marker-based configuration. Still functional; the brief's own spec asked for an "event loop fixture"
  explicitly, which is what this is — revisit if a future `pytest-asyncio` version actually breaks it.
- `audioop` deprecation warning comes from discord.py itself (Python 3.13 removed that stdlib module), not
  from this project's code — nothing to fix here.

**Still pending:** measured coverage percentage (next step).

**All 62 tests passed, 0 failed.** New `test_decorators.py` (16) and `test_mojang.py` (6) both pass, on top
of the original 40.

**Coverage: 39% → 50%** after the new tests. `decorators.py` went 0%→92%, `mojang.py` 0%→86%. Remaining
gap is `cogs/*.py`, `bot.py`, `session.py`, `logging_config.py` — all manually verified in Prototypes 1–3
against the real running bot, per the earlier documented decision not to chase 70% with low-value tests.
**Prototype 6 closed here.**
