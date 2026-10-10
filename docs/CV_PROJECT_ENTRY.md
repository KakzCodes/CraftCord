# CraftCord — CV Project Entry

**Status: PROVISIONAL.** Written at the end of Prototype 0 (repository audit)
from code inspection only. No automated test has been run, no container
has been built, and no live Discord/PostgreSQL/Pterodactyl connection has
been made yet. Do not copy this onto a live CV until Prototype 1 onward
produce verified results — see `PROJECT_EVIDENCE.md` for what's actually
been confirmed and what's still pending.

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

---

*Why no fourth bullet yet:* the brief this project follows caps the entry
at four bullets and requires every claim to be backed by measured
evidence, not estimated. A fourth bullet — covering test coverage, a
successful containerised run, or live command verification — gets added
once Prototype 1–6 actually produce that evidence, rather than being
filled with a placeholder now.
