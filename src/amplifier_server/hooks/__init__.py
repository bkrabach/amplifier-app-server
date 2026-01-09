"""Hook-based extension model for Amplifier Server.

Bundles can extend the server's capabilities by providing hooks that:
- Inject inputs (notifications, events, scheduled triggers)
- Process outputs (push notifications, webhooks, email)
- Observe and react to session events

This module provides the infrastructure for loading and managing these hooks.
"""

from amplifier_server.hooks.base import (
    ServerHook,
    InputHook,
    OutputHook,
    HookRegistry,
)

__all__ = [
    "ServerHook",
    "InputHook", 
    "OutputHook",
    "HookRegistry",
]
