from __future__ import annotations

import logging

try:
    from .dynamic_desired_retention.addon import setup

    setup()
except Exception:
    logging.getLogger(__name__).exception(
        "failed to initialize Dynamic Desired Retention"
    )
