"""Export the application's contract through FastAPI's native ``app.openapi``.

Owner: app.main.app; consumed by scripts/generate-client.sh.
Dependency provenance: the FastAPI distribution and digests pinned in uv.lock.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--app", default="app.main:app")
    args = parser.parse_args()

    from uvicorn.importer import import_from_string

    app = import_from_string(args.app)

    with args.output.open("w", encoding="utf-8") as stream:
        json.dump(app.openapi(), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
