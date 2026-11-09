"""Settings for Maaike's Red Rock entry. Never reads the TAOL database path."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_DATABASE_NAME = "maaike_redrock.db"
TAOL_DATABASE_NAMES = frozenset({"social_search.db", "seed_social_search.db"})


class MaaikeConfigError(RuntimeError):
    """Maaike's entry was pointed at the TAOL database."""


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def taol_database_paths() -> set[Path]:
    data = project_root() / "data"
    return {(data / name).resolve() for name in TAOL_DATABASE_NAMES}


def assert_separate_from_taol(path: Path) -> Path:
    """Refuse the live TAOL database and the bundled seed, by path and by name."""
    resolved = path.expanduser().resolve()
    if resolved.name in TAOL_DATABASE_NAMES or resolved in taol_database_paths():
        raise MaaikeConfigError(
            "Maaikes database mag niet het TAOL-bestand social_search.db of "
            "seed_social_search.db zijn. Laat MAAIKE_DATABASE_PATH leeg of wijs "
            "naar een apart bestand, standaard data/maaike_redrock.db."
        )
    return resolved


def database_path() -> Path:
    """Resolve Maaike's SQLite file. DATABASE_PATH from the TAOL app is ignored."""
    load_dotenv(override=False)
    raw = os.getenv("MAAIKE_DATABASE_PATH", "").strip()
    if not raw:
        raw = str(project_root() / "data" / DEFAULT_DATABASE_NAME)
    path = Path(raw)
    if not path.is_absolute():
        path = project_root() / path
    return assert_separate_from_taol(path)
