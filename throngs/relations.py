"""
Throng relationship graph: one throng can depend on another in a role.

E.g. Furniture Retail has Throng-Y as accountant, Throng-Z as delivery;
Throng-Z has Throng-Y as accountant, Throng-A as vehicle owner, Throng-B as parking vendor.
Used to inject relationship context into goal synthesis and runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from throngs.schemas import (
    ThrongGraphConfig,
    ThrongRef,
    ThrongRelationship,
    ThrongRole,
)

logger = logging.getLogger(__name__)


class ThrongGraph:
    """
    Directed graph of throngs and relationships.

    - owner_id --[role]--> provider_id means "owner depends on provider in role"
    - E.g. (FurnitureRetail, accountant, ThrongY): FurnitureRetail has ThrongY as accountant
    """

    def __init__(
        self,
        throngs: list[ThrongRef] | None = None,
        relationships: list[ThrongRelationship] | None = None,
    ) -> None:
        self._throngs: dict[str, ThrongRef] = {}
        self._by_owner: dict[str, list[tuple[ThrongRole, str]]] = {}  # owner_id -> [(role, provider_id)]
        self._by_provider: dict[str, list[tuple[str, ThrongRole]]] = {}  # provider_id -> [(owner_id, role)]

        for t in throngs or []:
            self._throngs[t.id] = t
        for r in relationships or []:
            self._add_edge(r.owner_id, r.role, r.provider_id)

    def _add_edge(self, owner_id: str, role: ThrongRole, provider_id: str) -> None:
        if owner_id not in self._by_owner:
            self._by_owner[owner_id] = []
        self._by_owner[owner_id].append((role, provider_id))
        if provider_id not in self._by_provider:
            self._by_provider[provider_id] = []
        self._by_provider[provider_id].append((owner_id, role))

    def get_throng(self, throng_id: str) -> Optional[ThrongRef]:
        """Return the ThrongRef for id, or None."""
        return self._throngs.get(throng_id)

    def who_provides_for(self, owner_id: str) -> list[tuple[ThrongRole, str]]:
        """List (role, provider_id) for everyone who provides a role to this owner."""
        return list(self._by_owner.get(owner_id, []))

    def who_depends_on(self, provider_id: str) -> list[tuple[str, ThrongRole]]:
        """List (owner_id, role) for everyone who depends on this provider."""
        return list(self._by_provider.get(provider_id, []))

    def roles_this_throng_provides(self, throng_id: str) -> list[tuple[str, ThrongRole]]:
        """As a provider: (owner_id, role) for each owner that depends on this throng."""
        return self.who_depends_on(throng_id)

    def roles_this_throng_uses(self, throng_id: str) -> list[tuple[ThrongRole, str]]:
        """As an owner: (role, provider_id) for each provider this throng depends on."""
        return self.who_provides_for(throng_id)

    def all_throng_ids(self) -> list[str]:
        """All known throng ids (from refs and edges)."""
        ids = set(self._throngs.keys())
        for k in self._by_owner:
            ids.add(k)
            for _, p in self._by_owner[k]:
                ids.add(p)
        for k in self._by_provider:
            ids.add(k)
            for o, _ in self._by_provider[k]:
                ids.add(o)
        return sorted(ids)

    def throng_id_for_persona(self, persona_name: str) -> Optional[str]:
        """Return throng id whose ThrongRef.persona_id matches persona_name, or None."""
        for ref in self._throngs.values():
            if ref.persona_id and ref.persona_id.strip():
                if ref.persona_id.strip() == persona_name.strip():
                    return ref.id
        return None

    def context_for_throng(self, throng_id: str) -> str:
        """
        Build a short narrative for goal synthesis: "You are X. You act as accountant for A, B. You depend on Y for delivery, Z for supplies."
        """
        lines = []
        ref = self.get_throng(throng_id)
        label = ref.label or throng_id if ref else throng_id
        lines.append(f"You are throng \"{label}\" (id: {throng_id}).")

        # Roles this throng provides to others (I am accountant for X, delivery for Y)
        provided = self.roles_this_throng_provides(throng_id)
        if provided:
            parts = [f"you act as {role.value} for {owner_id}" for owner_id, role in provided]
            lines.append("In this network: " + "; ".join(parts) + ".")

        # Roles this throng uses from others (I depend on Z for delivery, W for supplies)
        used = self.roles_this_throng_uses(throng_id)
        if used:
            parts = [f"{provider_id} as {role.value}" for role, provider_id in used]
            lines.append("You depend on: " + "; ".join(parts) + ".")

        return " ".join(lines)

    @classmethod
    def from_config(cls, config: ThrongGraphConfig) -> ThrongGraph:
        return cls(throngs=config.throngs, relationships=config.relationships)

    @classmethod
    def load_json(cls, path: str | Path) -> ThrongGraph:
        """Load from a JSON file (throngs + relationships)."""
        path = Path(path)
        if not path.exists():
            logger.warning("Throng graph file not found: %s", path)
            return cls()
        data = json.loads(path.read_text())
        config = ThrongGraphConfig.model_validate(data)
        return cls.from_config(config)

    @classmethod
    def load_yaml(cls, path: str | Path) -> ThrongGraph:
        """Load from YAML if pyyaml available."""
        path = Path(path)
        if not path.exists():
            logger.warning("Throng graph file not found: %s", path)
            return cls()
        try:
            import yaml
            data = yaml.safe_load(path.read_text())
        except ImportError:
            logger.warning("PyYAML not installed; cannot load %s", path)
            return cls()
        config = ThrongGraphConfig.model_validate(data)
        return cls.from_config(config)


def load_throng_graph(path: str | Path | None) -> ThrongGraph:
    """Load from JSON or YAML by extension; return empty graph if path is None or missing."""
    if path is None:
        return ThrongGraph()
    path = Path(path)
    if not path.exists():
        return ThrongGraph()
    if path.suffix.lower() in (".yaml", ".yml"):
        return ThrongGraph.load_yaml(path)
    return ThrongGraph.load_json(path)
