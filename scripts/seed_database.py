#!/usr/bin/env python
"""Reset the database and load vendors / POs / PO history from sample_data/*.csv.

    python scripts/seed_database.py            # run from the repo root, with the backend venv active
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import seeder  # noqa: E402

if __name__ == "__main__":
    print("Seeded:", seeder.reset_database())
