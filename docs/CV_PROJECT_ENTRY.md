# CraftCord — CV Project Entry

**Status:** Local source, tests, and container image verified; current-checkout
Discord login and live Pterodactyl/RCON integration pending.

**CraftCord** — Discord bot for Minecraft server management via Pterodactyl

*Personal project · Python 3.12, PostgreSQL, Docker Compose*

- Engineered a Discord bot for Minecraft server administration, with 20 slash
  commands covering server controls, player account linking, admin workflows,
  and utility commands.
- Built an asynchronous Python backend using SQLAlchemy and PostgreSQL, with
  Alembic migrations, repository-based persistence, audit logging, and
  permission checks.
- Integrated typed HTTP clients for Pterodactyl and Mojang, RCON-backed player
  features, validated configuration, and safe retries for idempotent API reads;
  containerised the service with Docker Compose and startup migrations.
- Verified 132 automated tests, including PostgreSQL integration and mocked
  API/command paths, at 88% branch-aware coverage. GitHub Actions passes the
  lint, dependency-audit, coverage, Compose, and Docker image checks on master;
  live panel and RCON integrations remain unverified.

**Technology:** Python 3.12, discord.py, HTTPX, SQLAlchemy, PostgreSQL,
Alembic, Pydantic, Docker Compose, pytest, Ruff.
