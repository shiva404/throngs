from __future__ import annotations

import json
import logging
from pathlib import Path

from throngs.schemas import LoginCredentials, PersonaDNA

logger = logging.getLogger(__name__)


class PersonaEngine:
    """Loads and manages Persona DNA configurations."""

    def __init__(self) -> None:
        self._personas: dict[str, PersonaDNA] = {}
        self._credentials: dict[str, LoginCredentials] = {}

    def load_from_file(self, path: str | Path) -> list[PersonaDNA]:
        """Load personas from a JSON file containing an array of persona configs."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Persona file not found: {path}")

        data = json.loads(path.read_text())
        personas_raw = data if isinstance(data, list) else data.get("personas", [])
        personas = [PersonaDNA.model_validate(p) for p in personas_raw]

        for p in personas:
            self._personas[p.id] = p
            logger.info("Loaded persona: %s (%s)", p.name, p.id)

        return personas

    def load_credentials(self, path: str | Path, company: str | None = None) -> None:
        """Load login credentials from a JSON file.

        The file can be structured in two ways:

        **Multi-company** (preferred)::

            { "Acme": { "PersonaName": { ... } }, "OtherCo": { ... } }

        When *company* is supplied the matching top-level key is used.
        When *company* is ``None`` the first company in the file is used.

        **Legacy flat** (auto-detected — no nested company keys)::

            { "PersonaName": { "email": "...", ... } }
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Credentials file not found: {path}")

        data = json.loads(path.read_text())

        if self._is_multi_company(data):
            available = list(data.keys())
            if company is None:
                company = available[0]
                logger.info(
                    "No --company specified; defaulting to '%s' (available: %s)",
                    company,
                    available,
                )
            if company not in data:
                raise ValueError(
                    f"Company '{company}' not found in credentials file. "
                    f"Available companies: {available}"
                )
            persona_creds = data[company]
        else:
            persona_creds = data

        for name, cred_data in persona_creds.items():
            self._credentials[name] = LoginCredentials.model_validate(cred_data)
            logger.info("Loaded credentials for persona: %s", name)

    @staticmethod
    def list_companies(path: str | Path) -> list[str]:
        """Return the company names available in a credentials file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Credentials file not found: {path}")
        data = json.loads(path.read_text())
        if PersonaEngine._is_multi_company(data):
            return list(data.keys())
        return []

    @staticmethod
    def _is_multi_company(data: dict) -> bool:
        """Detect whether the credentials dict uses the multi-company format.

        In multi-company format every top-level value is a dict of dicts.
        In flat format the top-level values are credential dicts containing
        an ``email`` key.
        """
        if not data:
            return False
        first_value = next(iter(data.values()))
        return isinstance(first_value, dict) and "email" not in first_value

    def get_credentials(self, persona_name: str) -> LoginCredentials | None:
        """Look up login credentials by persona name."""
        return self._credentials.get(persona_name)

    def load_persona(self, persona: PersonaDNA) -> PersonaDNA:
        """Register a single persona directly."""
        self._personas[persona.id] = persona
        return persona

    def get(self, persona_id: str) -> PersonaDNA:
        return self._personas[persona_id]

    def list_all(self) -> list[PersonaDNA]:
        return list(self._personas.values())

    def build_system_prompt_fragment(self, persona: PersonaDNA) -> str:
        """Generate the persona-specific portion of the LLM system prompt."""
        tech_desc = _literacy_label(persona.tech_literacy)
        domain_desc = _literacy_label(persona.domain_literacy)

        patience_desc = _patience_label(persona.patience_budget)
        lines = [
            f"You are roleplaying as \"{persona.name}\".",
            f"Tech Literacy: {persona.tech_literacy}/10 ({tech_desc}).",
            f"Domain (Accounting) Literacy: {persona.domain_literacy}/10 ({domain_desc}).",
            f"Patience Level: {patience_desc}. You are willing to explore and try "
            f"different things before giving up.",
        ]
        if persona.trigger_words:
            lines.append(
                f"Words that confuse or stress you: {', '.join(persona.trigger_words)}."
            )
        if persona.friendly_words:
            lines.append(
                f"Words you actively look for and feel comfortable with: {', '.join(persona.friendly_words)}."
            )
        if persona.description:
            lines.append(f"Background: {persona.description}")

        return "\n".join(lines)


def _literacy_label(level: int) -> str:
    if level <= 3:
        return "Low — struggles with unfamiliar UI patterns"
    if level <= 6:
        return "Medium — comfortable with common patterns"
    return "High — can navigate complex and hidden UI features"


def _patience_label(budget: int) -> str:
    if budget <= 30:
        return "Low — gets frustrated relatively quickly but still tries a few things"
    if budget <= 50:
        return "Moderate — willing to spend a fair amount of time figuring things out"
    return "High — very persistent, will keep trying different approaches"
