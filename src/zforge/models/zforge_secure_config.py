"""Secure configuration models.

ZForgeSecureConfig and LlmConnectorConfiguration per
docs/Data and File Specifications.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LlmConnectorConfiguration:
    """Credential key/value pairs for a single LLM connector."""

    connector_name: str
    values: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connectorName": self.connector_name,
            "values": dict(self.values),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LlmConnectorConfiguration:
        return cls(
            connector_name=data["connectorName"],
            values=dict(data.get("values", {})),
        )


@dataclass
class ZForgeSecureConfig:
    """Secure config held in platform keychain via keyring."""

    connectors: dict[str, LlmConnectorConfiguration] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "connectors": {
                k: v.to_dict() for k, v in self.connectors.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ZForgeSecureConfig:
        connectors_data = data.get("connectors", {})
        return cls(
            connectors={
                k: LlmConnectorConfiguration.from_dict(v)
                for k, v in connectors_data.items()
            }
        )
