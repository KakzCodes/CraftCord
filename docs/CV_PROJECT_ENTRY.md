# CraftCord — CV Project Entry

**Status: Prototype verified; external panel/RCON integration pending.** The
automated suite meets the configured coverage threshold (75% vs. 70%). Real
Pterodactyl and Minecraft RCON integration has not been tested. See
`PROJECT_EVIDENCE.md` for the dated evidence and remaining limitations.

---

**CraftCord** — Discord bot for Minecraft server management via Pterodactyl
*Personal project · Python, PostgreSQL, Docker · in development*

- Designed and implemented the backend for a Discord bot (Python 3.12,
  discord.py slash commands) that lets a Discord community start, stop,
  restart and monitor Minecraft servers hosted on a Pterodactyl panel,
  removing the need for end users to have direct panel access.
- Built a layered architecture using SQLAlchemy 2.0's async ORM with
  Alembic-managed PostgreSQL migrations, a repository pattern isolating
  all SQL from command handlers, and typed async HTTP clients (httpx) for
  the Pterodactyl and Mojang APIs with retry/backoff and structured
  (structlog) error handling.
- Engineered a composable decorator stack enforcing guild registration,
  target-server resolution and role-based admin permissions consistently
  across 20 slash commands, and containerised the stack with Docker and
  Docker Compose, including an Alembic-migrate-on-startup entrypoint.
- Validated the system through both automated and live testing: 111
  automated tests (unit and integration, including database-constraint
  and cascade-delete checks run against a real containerised PostgreSQL
  instance via testcontainers, 75% statement coverage) passing with zero
  failures, and the full Docker Compose stack verified end-to-end —
  migrations, Discord authentication, slash-command registration, and
  live command execution all confirmed working in a real Discord server.

---

*Still incomplete:* verify integration with a real Pterodactyl panel and
Minecraft server when available, and complete the broader security/quality
review. The API tests currently use mocks.
