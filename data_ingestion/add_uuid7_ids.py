"""Ensure every record in the ingestion data files carries a `unique_reference_id`
(a UUIDv7) alongside its existing `id`.

Non-destructive: `id` and every other field is left untouched. A record that
already has a `unique_reference_id` (the source system already assigns these)
is left as-is, so this is safe to re-run.
"""

import json
from pathlib import Path

from uuid_utils.compat import uuid7

DATA_DIR = Path(__file__).parent / "data"

ID_KEY = "id"
UUID_KEY = "unique_reference_id"


def _add_uuid7(node: object) -> None:
    if isinstance(node, dict):
        if ID_KEY in node and UUID_KEY not in node:
            node[UUID_KEY] = str(uuid7())
        for value in node.values():
            _add_uuid7(value)
    elif isinstance(node, list):
        for item in node:
            _add_uuid7(item)


def add_uuid7_ids(path: Path) -> None:
    data = json.loads(path.read_text())
    for case in data.get("result", []):
        _add_uuid7(case)
    path.write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        print(f"No data files found in {DATA_DIR}")
        return
    for path in files:
        print(f"Adding uuid7 ids to {path.name}...")
        add_uuid7_ids(path)
    print("Done.")


if __name__ == "__main__":
    main()
