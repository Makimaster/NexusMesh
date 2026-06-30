import logging
import sys

from app.config.settings import settings

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    if not root.handlers:
        root.addHandler(handler)

    _configured = True


_configure()

log = logging.getLogger("nexusmesh")
