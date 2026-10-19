# CraftCord — CV Project Entry

**Status: Local prototype verified; live panel/RCON integration pending.**
Automated coverage is 83% against a 70% target. See `PROJECT_EVIDENCE.md`
for evidence and remaining limitations.

---

**CraftCord** — Discord bot for Minecraft server management via Pterodactyl
*Personal project · Python, PostgreSQL, Docker · in development*

- Built CraftCord, a Discord bot that lets gaming communities manage
  Pterodactyl-hosted Minecraft servers through slash commands, with player
  account linking and in-game status features.
- Implemented an asynchronous Python backend with SQLAlchemy, PostgreSQL,
  Alembic migrations and repository-based persistence; integrated typed
  HTTP clients for Pterodactyl and Mojang with retries and structured,
  user-safe error handling.
- Delivered 20 slash commands across server, player, admin and utility
  workflows, with shared guild/server resolution, audit logging and
  Manage Server access control; containerised the bot and database using
  Docker Compose with migrations on startup.
- Validated with 121 passing automated tests and 83% statement coverage,
  including PostgreSQL integration and mocked API/command tests. The Docker
  bot authenticated and synchronised commands in Discord, and at least two
  commands were confirmed responding in the live test server; real panel
  and Minecraft RCON integration remain untested.

---

*Still incomplete:* verify real Pterodactyl and Minecraft RCON integration
when available. API tests use mocks; dependency vulnerability scanning and
a deployment threat review are pending.
