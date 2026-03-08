"""ZWorld data model and related entity types.

Implements the Z-World schema per docs/Z-World.md.
Persistence is handled by ZWorldManager via Z-Bundles (KVP + LanceDB + KùzuDB);
this module defines the in-memory representation only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CharacterName:
    """A name for a character, with optional context (e.g. 'formal name')."""

    name: str
    context: str | None = None


@dataclass
class Character:
    """A character in the world with stable ID, names, and history."""

    id: str
    names: list[CharacterName] = field(default_factory=list)
    history: str = ""


@dataclass
class Location:
    """A location with optional nested sublocations."""

    id: str
    name: str
    description: str = ""
    sublocations: list[Location] = field(default_factory=list)


@dataclass
class Event:
    """A significant occurrence with a description and time reference."""

    description: str
    time: str = ""


@dataclass
class Mechanic:
    """A world mechanic describing how the world operates."""

    text: str


@dataclass
class Trope:
    """A recurring story element or narrative style convention."""

    text: str


@dataclass
class Species:
    """A notable species in the world."""

    text: str


@dataclass
class Occupation:
    """An occupation of narrative significance."""

    text: str


@dataclass
class Relationship:
    """A typed link between two entity IDs."""

    from_id: str
    to_id: str
    type: str


@dataclass
class ZWorld:
    """Complete world specification per docs/Z-World.md."""

    title: str
    slug: str
    uuid: str = ""
    summary: str = ""
    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    mechanics: list[Mechanic] = field(default_factory=list)
    tropes: list[Trope] = field(default_factory=list)
    species: list[Species] = field(default_factory=list)
    occupations: list[Occupation] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)

    def all_entities(self) -> list[tuple[str, str, str, str]]:
        """Return all entities as (entity_id, entity_type, display_name, text_chunk) tuples.

        Used by ZWorldManager for vector store encoding.
        """
        entities: list[tuple[str, str, str, str]] = []

        for c in self.characters:
            display = c.names[0].name if c.names else c.id
            names_str = ", ".join(
                f"{n.name} ({n.context})" if n.context else n.name
                for n in c.names
            )
            text = f"Character: {names_str}. {c.history}"
            entities.append((c.id, "character", display, text))

        def _collect_locations(locs: list[Location]) -> None:
            for loc in locs:
                text = f"Location: {loc.name}. {loc.description}"
                entities.append((loc.id, "location", loc.name, text))
                _collect_locations(loc.sublocations)

        _collect_locations(self.locations)

        for i, ev in enumerate(self.events):
            eid = f"event-{i}"
            text = f"Event: {ev.description}. Time: {ev.time}"
            entities.append((eid, "event", ev.description[:50], text))

        for i, m in enumerate(self.mechanics):
            entities.append((f"mechanic-{i}", "mechanic", m.text[:50], f"Mechanic: {m.text}"))

        for i, t in enumerate(self.tropes):
            entities.append((f"trope-{i}", "trope", t.text[:50], f"Trope: {t.text}"))

        for i, s in enumerate(self.species):
            entities.append((f"species-{i}", "species", s.text[:50], f"Species: {s.text}"))

        for i, o in enumerate(self.occupations):
            entities.append((f"occupation-{i}", "occupation", o.text[:50], f"Occupation: {o.text}"))

        return entities
