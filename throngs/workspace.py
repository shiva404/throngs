"""Software workspace models — multi-app support for service businesses.

A ``SoftwareRegistry`` maps software types (accounting, email) to URLs.
A ``BusinessTask`` enriches each goal-chain step with which software to use.
A ``WorkflowRouter`` maps business events to the appropriate software.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SoftwareEntry(BaseModel):
    """One application in the business's software stack."""

    software_type: str          # "accounting", "email"
    url: str                    # "https://app.qbo.intuit.com"
    label: str = ""             # "QuickBooks Online"
    login_required: bool = True
    is_primary: bool = False    # which app the persona defaults to when idle


class SoftwareRegistry(BaseModel):
    """Available software applications for a business persona."""

    entries: list[SoftwareEntry] = Field(default_factory=list)

    def get(self, software_type: str) -> Optional[SoftwareEntry]:
        """Look up a software entry by type."""
        for e in self.entries:
            if e.software_type == software_type:
                return e
        return None

    def primary(self) -> SoftwareEntry:
        """Return the primary (default) application."""
        for e in self.entries:
            if e.is_primary:
                return e
        # Fallback to first entry
        if self.entries:
            return self.entries[0]
        raise ValueError("SoftwareRegistry has no entries")

    def types(self) -> list[str]:
        return [e.software_type for e in self.entries]

    def to_prompt_fragment(self) -> str:
        """Generate a text block for LLM prompts listing available software."""
        if not self.entries:
            return ""
        lines = []
        for e in self.entries:
            label = e.label or e.software_type
            primary_tag = " (primary)" if e.is_primary else ""
            lines.append(f"- {e.software_type}: {label}{primary_tag} — {e.url}")
        return "\n".join(lines)

    @classmethod
    def from_file(cls, path: str | Path) -> SoftwareRegistry:
        """Load a software registry from a JSON file."""
        data = json.loads(Path(path).read_text())
        entries = [SoftwareEntry(**e) for e in data.get("software", [])]
        return cls(entries=entries)

    @classmethod
    def from_single_url(cls, url: str, label: str = "Application") -> SoftwareRegistry:
        """Backward compat — wrap a single URL into a one-entry registry."""
        return cls(entries=[
            SoftwareEntry(
                software_type="primary",
                url=url,
                label=label,
                is_primary=True,
            )
        ])


class BusinessTask(BaseModel):
    """One task in a goal chain, annotated with which software to use."""

    description: str            # "Create estimate for Alice Smith's drain repair"
    software_type: str = ""     # "accounting" | "email" | "" (no software)
    url: str = ""               # Resolved from SoftwareRegistry at runtime
    triggered_by: str = ""      # "phone_call:abc123" | "email:def456" | ""

    def to_goal_chain_dict(self) -> dict:
        """Serialize for AgentState.goal_chain (LangGraph needs JSON-serializable)."""
        return {
            "description": self.description,
            "software_type": self.software_type,
            "url": self.url,
            "triggered_by": self.triggered_by,
        }

    @classmethod
    def from_plain_goal(cls, goal: str, software_type: str = "primary", url: str = "") -> BusinessTask:
        """Wrap a plain goal string into a BusinessTask (backward compat)."""
        return cls(description=goal, software_type=software_type, url=url)


class WorkflowRouter:
    """Maps business events to the appropriate software type.

    Default mappings can be overridden via the software stack JSON file
    (``event_routes`` key).
    """

    DEFAULT_ROUTES: dict[str, str] = {
        "PHONE_CALL": "",                   # phone call itself is just talking
        "CREATE_ESTIMATE": "accounting",
        "SEND_ESTIMATE": "accounting",
        "SEND_INVOICE": "accounting",
        "RECORD_PAYMENT": "accounting",
        "CHECK_PL": "accounting",
        "CHECK_BANK_FEED": "accounting",
        "CREATE_PO": "accounting",
        "CHECK_EMAIL": "email",
        "REPLY_EMAIL": "email",
        "SEND_ESTIMATE_EMAIL": "email",
    }

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._routes = dict(self.DEFAULT_ROUTES)
        if overrides:
            self._routes.update(overrides)

    def route_event(self, event_type: str) -> str:
        """Return the software_type for a business event."""
        return self._routes.get(event_type, "")

    @classmethod
    def from_file(cls, path: str | Path) -> WorkflowRouter:
        """Load from a software stack JSON (reads ``event_routes`` key)."""
        data = json.loads(Path(path).read_text())
        overrides = data.get("event_routes", {})
        return cls(overrides=overrides)
