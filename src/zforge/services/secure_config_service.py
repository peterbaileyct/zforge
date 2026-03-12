"""Secure configuration persistence service.

Loads/saves ZForgeSecureConfig via keyring (service name "zforge").
Implements: src/zforge/services/secure_config_service.py per docs/ER Diagram.md.
"""

from __future__ import annotations

import json

import keyring

from zforge.models.zforge_secure_config import ZForgeSecureConfig


_SERVICE_NAME = "zforge"
_KEY_NAME = "secure_config"


class SecureConfigService:
    """Persists ZForgeSecureConfig in the platform keychain via keyring."""

    def load(self) -> ZForgeSecureConfig:
        """Load secure config from keyring, or return empty if unavailable."""
        raw = keyring.get_password(_SERVICE_NAME, _KEY_NAME)
        if raw:
            data = json.loads(raw)
            return ZForgeSecureConfig.from_dict(data)
        return ZForgeSecureConfig()

    def save(self, config: ZForgeSecureConfig) -> None:
        """Save secure config to keyring."""
        raw = json.dumps(config.to_dict())
        keyring.set_password(_SERVICE_NAME, _KEY_NAME, raw)
