"""Latency budgets: the spec targets gate local runs; shared 2-vCPU CI runners get 1.5x headroom."""

import os

SLACK = 1.5 if os.environ.get("CI") else 1.0
