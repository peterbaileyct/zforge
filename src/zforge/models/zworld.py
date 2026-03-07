"""ZWorld data model and related types.

Implements the ZWorld schema per docs/ZWorld.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CharacterName:
    name: str
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.context is not None:
            d["context"] = self.context
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterName:
        return cls(name=data["name"], context=data.get("context"))


@dataclass
class Character:
    id: str
    names: list[CharacterName]
    history: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "names": [n.to_dict() for n in self.names],
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Character:
        return cls(
            id=data["id"],
            names=[CharacterName.from_dict(n) for n in data["names"]],
            history=data["history"],
        )


@dataclass
class Relationship:
    character_a_id: str
    character_b_id: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_a_id": self.character_a_id,
            "character_b_id": self.character_b_id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Relationship:
        return cls(
            character_a_id=data["character_a_id"],
            character_b_id=data["character_b_id"],
            description=data["description"],
        )


@dataclass
class WorldEvent:
    description: str
    date: str

    def to_dict(self) -> dict[str, Any]:
        return {"description": self.description, "date": self.date}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorldEvent:
        return cls(description=data["description"], date=data["date"])


@dataclass
class Location:
    id: str
    name: str
    description: str
    sublocations: list[Location] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }
        if self.sublocations:
            d["sublocations"] = [s.to_dict() for s in self.sublocations]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Location:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            sublocations=[
                cls.from_dict(s) for s in data.get("sublocations", [])
            ],
        )


@dataclass
class ZWorld:
    id: str
    name: str
    locations: list[Location] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    events: list[WorldEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "locations": [loc.to_dict() for loc in self.locations],
            "characters": [c.to_dict() for c in self.characters],
            "relationships": [r.to_dict() for r in self.relationships],
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ZWorld:
        return cls(
            id=data["id"],
            name=data["name"],
            locations=[Location.from_dict(l) for l in data.get("locations", [])],
            characters=[Character.from_dict(c) for c in data.get("characters", [])],
            relationships=[
                Relationship.from_dict(r) for r in data.get("relationships", [])
            ],
            events=[WorldEvent.from_dict(e) for e in data.get("events", [])],
        )
