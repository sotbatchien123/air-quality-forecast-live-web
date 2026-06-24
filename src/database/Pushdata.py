"""Backward-compatible entry point for live database management.

The old implementation appended every raw CSV to VARCHAR-only tables and could
overwrite the setup script. Use the typed, idempotent live schema instead.
"""

from manage_live_database import main


if __name__ == "__main__":
    main()
