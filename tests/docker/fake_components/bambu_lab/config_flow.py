"""Trivial config flow so the fake's seeded config entry sets up like the real one.

Home Assistant only sets up a stored config entry for an integration that declares
``config_flow: true`` and ships a flow (the real Bambu Lab integration does). The e2e
tiers seed the entry directly in ``.storage``; this flow exists so HA accepts and sets
it up (and so hassfest is satisfied).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

DOMAIN = "bambu_lab"


class BambuFakeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step flow that creates the fake printer entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title="X1 Carbon", data={"serial": "E2E0001", "name": "X1 Carbon"}
        )
