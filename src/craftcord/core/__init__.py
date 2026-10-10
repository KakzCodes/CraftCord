"""Domain layer: external API clients, the embed design system, and domain exceptions.

Nothing in `core/` depends on discord.py's `commands`/cog machinery or on
the database layer — it's the part of CraftCord that would be reusable
outside a Discord bot (e.g. from a future web dashboard in Iteration 2).
The one exception is `core/embeds.py`, which necessarily depends on
`discord.Embed` since embed construction *is* its job.
"""

from __future__ import annotations
