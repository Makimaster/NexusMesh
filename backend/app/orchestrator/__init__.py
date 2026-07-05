"""M6 orchestrator public API.

External modules such as M7 should import ``Coordinator`` from this package.
"""

import logging

_QUIET_IMPORT_LOGGERS = ("httpcore", "httpcore.connection", "LiteLLM", "litellm")
_PREVIOUS_LOG_LEVELS = {
    logger_name: logging.getLogger(logger_name).level
    for logger_name in _QUIET_IMPORT_LOGGERS
}

try:
    for logger_name in _QUIET_IMPORT_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    from app.orchestrator.coordinator import Coordinator
finally:
    for logger_name, previous_level in _PREVIOUS_LOG_LEVELS.items():
        logging.getLogger(logger_name).setLevel(previous_level)

__all__ = ["Coordinator"]
