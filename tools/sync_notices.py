#!/usr/bin/env python3
"""Copy the licence materials into the package, where installs can see them.

The BSD-3-Clause licence on the bundled coefficient tables requires its notice
to accompany redistribution, and a wheel is a redistribution. Files beside the
repository do not survive `pip install`, so the package carries its own copy --
and two copies can drift, which is what `test_the_packaged_notice_matches_the_
repository_copy` exists to catch. Run this after editing either original.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "tms52xx" / "data" / "licenses"

PAIRS = [
    (ROOT / "THIRD_PARTY_NOTICES.md", TARGET / "THIRD_PARTY_NOTICES.md"),
    (ROOT / "LICENSES" / "BSD-3-Clause.txt", TARGET / "BSD-3-Clause.txt"),
]


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    changed = []
    for source, destination in PAIRS:
        if not source.exists():
            raise SystemExit("missing %s" % source)
        if not destination.exists() or \
                destination.read_bytes() != source.read_bytes():
            shutil.copyfile(source, destination)
            changed.append(destination)
    for path in changed:
        print("updated %s" % path.relative_to(ROOT))
    print("licence materials in sync" if not changed else "done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
