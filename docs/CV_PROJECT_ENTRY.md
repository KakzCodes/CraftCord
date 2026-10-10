# CraftCord — CV Project Entry

**Status: PARTIALLY VERIFIED.** Updated at the end of Prototype 1 (local
startup). The first bullet below now rests on an actually-executed,
working system — the others are still design/implementation claims from
code inspection, pending Prototypes 2–6. See `PROJECT_EVIDENCE.md` for the
full, dated verification log.

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
- Verified the full stack end-to-end in Docker Compose: PostgreSQL
  reaching a healthy state, Alembic migrations applying cleanly and
  idempotently on restart, the bot authenticating with Discord and
  registering 20 slash commands, commands responding correctly in a live
  test server, and the process shutting down cleanly on signal.

---

*Still pending before the remaining bullets can be strengthened further:*
automated test results and coverage (Prototype 6), and any interaction
with a real Pterodactyl panel or Minecraft server (Prototype 7) — see
`PROJECT_EVIDENCE.md`.
