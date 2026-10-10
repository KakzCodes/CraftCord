# Command Reference

All commands are slash commands. **Every error response is ephemeral**,
regardless of what's noted below — the "Ephemeral?" column here describes
the *success* response only. "Public" means visible to the whole channel
(discoverable, not whispered) — this is deliberate for server actions so
the community can see who did what.

## `/server`

| Command | Description | Required Permission | Ephemeral (success)? |
| --- | --- | --- | --- |
| `/server start [server]` | Start a Minecraft server. | None | No (public) |
| `/server stop [server]` | Stop a Minecraft server. | None | Confirmation prompt is ephemeral; the result announcement is public |
| `/server restart [server]` | Restart a Minecraft server. | None | No (public) |
| `/server status [server]` | Show live CPU/RAM/disk/player status. | None | No (public) |
| `/server info [server]` | Show registered metadata and 7-day known uptime. | None | No (public) |
| `/server list` | List all servers registered to this guild. | None | No (public) |
| `/server ip [server]` | Get the server's connect address. | None | No (public) |

## Players

| Command | Description | Required Permission | Ephemeral (success)? |
| --- | --- | --- | --- |
| `/link <minecraft_username>` | Link your Discord account to a Minecraft username. | None | Yes |
| `/unlink` | Remove your linked Minecraft account. | None | Yes |
| `/whois [discord_user]` | Show a user's linked Minecraft account and best-effort online status. | None | No (public) |
| `/online [server]` | List players currently online. | None | No (public) |
| `/locate <minecraft_username> [server]` | Find a player's current coordinates. | None | No (public) |

## `/admin`

Every command below requires **`Manage Server`** permission, or
membership in the configured bot-admin role (`CraftCord Admin`, until a
per-guild configurable role is added in a later iteration).

| Command | Description | Required Permission | Ephemeral (success)? |
| --- | --- | --- | --- |
| `/admin register-server <name> <pterodactyl_uuid> <pterodactyl_numeric_id> [mc_version] [is_default]` | Link a Minecraft server that **already exists** on the panel. Validates the UUID against the panel first; enforces the grass-tier limit of 1 server per guild. | Manage Server (or bot-admin role) | Yes |
| `/admin create-server <name> [is_default]` | Provision a **brand-new** server on the panel from a fixed template, then register it. Disabled unless the creation template is configured — see `.env.example`. | Manage Server (or bot-admin role) | Yes |
| `/admin unregister-server <name>` | Remove a registered server. Asks for confirmation first. | Manage Server (or bot-admin role) | Yes |
| `/admin set-default <name>` | Set a server as this guild's default. | Manage Server (or bot-admin role) | Yes |

## Meta

| Command | Description | Required Permission | Ephemeral (success)? |
| --- | --- | --- | --- |
| `/help` | Show a paginated command reference, grouped by category. | None | Yes |
| `/ping` | Check gateway and Pterodactyl API latency. | None | Yes |
| `/invite` | Get the bot's OAuth2 invite link. | None | Yes |
| `/botinfo` | Show version, uptime, guild count, registered-server count, and DB pool status. | None | Yes |
