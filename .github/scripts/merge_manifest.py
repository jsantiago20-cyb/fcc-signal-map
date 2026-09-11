"""Graft one survey entry onto whatever surveys.json is on the branch now.

A run can spend five minutes harvesting while another run publishes its own
pack, so rebasing the harvested manifest hits a conflict every time. Instead the
commit step resets to the current branch and calls this: take our entry out of
the manifest we built, drop it into the fresh one, leave every other entry as it
stands. Same shape and ordering as nbm_site.write_pack.

    python .github/scripts/merge_manifest.py <harvested surveys.json> <slug>
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    harvested, slug = sys.argv[1], sys.argv[2]
    mine = json.load(open(harvested, encoding="utf-8"))
    entry = next(s for s in mine["surveys"] if s.get("slug") == slug)

    path = os.path.join(ROOT, "surveys.json")
    man = {"surveys": []}
    if os.path.exists(path):
        try:
            man = json.load(open(path, encoding="utf-8"))
        except Exception:
            pass

    man["surveys"] = [s for s in man.get("surveys", []) if s.get("slug") != slug] + [entry]
    man["surveys"].sort(key=lambda s: s["name"])
    man.setdefault("default", man["surveys"][0]["slug"])
    json.dump(man, open(path, "w", encoding="utf-8"), indent=1)
    print("manifest now lists {} survey(s), including {}".format(len(man["surveys"]), slug))


if __name__ == "__main__":
    main()
