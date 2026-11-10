"""API tests."""

import os

# Settings has no default env, and importing app.main builds the app: set one before any test module loads.
os.environ.setdefault("ENV", "test")
