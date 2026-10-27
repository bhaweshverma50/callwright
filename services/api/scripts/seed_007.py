"""Quickstart fixtures for spec 007 (T012). See ``app.dev.seed_quality``.

    uv run python -m scripts.seed_007 --workspace ws_... \\
        --dsn postgresql://callwright:callwright@localhost:55432/db
"""

from app.dev.seed_quality import main

if __name__ == "__main__":
    main()
