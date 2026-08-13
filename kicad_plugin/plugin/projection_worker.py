from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from local_projection import project_step
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "step2graphics"))
    from local_projection import project_step


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step_file", type=Path)
    parser.add_argument("axis", choices=["+X", "-X", "+Y", "-Y", "+Z", "-Z"])
    parser.add_argument("tolerance", type=float)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    projection = project_step(args.step_file, args.axis, args.tolerance)
    args.output.write_text(
        json.dumps(projection, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
