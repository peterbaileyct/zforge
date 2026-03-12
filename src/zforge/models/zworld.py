"""ZWorld KVP data model.

Implements the Z-World key-value metadata per docs/Z-World.md and
docs/World Generation.md.  Entity data (characters, locations, events,
etc.) is stored schema-lessly in the Z-Bundle's LanceDB vector store and
KùzuDB property graph; this module holds only the KVP fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ZWorld:
    """Z-World KVP metadata per docs/World Generation.md § Implementation."""

    title: str
    slug: str
    uuid: str
    summary: str
    setting_era: str = ""
    source_canon: list[str] = field(default_factory=list)
    content_advisories: list[str] = field(default_factory=list)
