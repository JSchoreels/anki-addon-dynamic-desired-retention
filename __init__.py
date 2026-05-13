from __future__ import annotations

import logging
import sys

try:
    from . import dynamic_desired_retention as _stable_package
    from .dynamic_desired_retention import api as _stable_api
    from .dynamic_desired_retention.api import effective_desired_retention

    sys.modules.setdefault("dynamic_desired_retention", _stable_package)
    sys.modules.setdefault("dynamic_desired_retention.api", _stable_api)
except ImportError:
    from dynamic_desired_retention.api import effective_desired_retention

try:
    from .dynamic_desired_retention.addon import setup

    setup()
except Exception:
    logging.getLogger(__name__).exception(
        "failed to initialize Dynamic Desired Retention"
    )

__all__ = ["effective_desired_retention"]
