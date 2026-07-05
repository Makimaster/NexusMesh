"""M6 orchestrator public API.

External modules such as M7 should import ``Coordinator`` from this package.
"""

from app.orchestrator.coordinator import Coordinator

__all__ = ["Coordinator"]
