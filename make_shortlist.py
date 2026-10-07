#!/usr/bin/env python3
"""Turn roles.csv into a readable shortlist.

    python make_shortlist.py            # reads roles.csv, writes SHORTLIST.md
    python make_shortlist.py mine.csv

The verdict columns are printed in full, including the removals, because the
list of what came off is the half that says whether the filter was any good.
"""

import collections
import csv
import io
import sys


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "roles.csv"
    dst = sys.argv[2] if len(sys.argv) > 2 else "SHORTLIST.md"

    rows = list(csv.DictReader(io.open(src, encoding="utf-8")))
    if not rows:
        print("no rows in %s" % src)
        return

    pick = lambda v: [r for r in rows if r["verdict"] == v]
    op, ch, un, bl = pick("OPEN"), pick("CHECK"), pick("UNCLEAR"), pick("BLOCKED")
    stated = sum(1 for r in rows if r["confidence"] == "stated")
    companies = len({r["company"].lower() for r in rows})
    clean = lambda s, n: s[:n].replace("|", "/")

    with io.open(dst, "w", encoding="utf-8") as f:
        w = f.write
        w("# Remote GTM roles\n\n")
        w("Built with `pull_roles.py`: six public job feeds, no API keys, no\n")
        w("accounts, standard library only.\n\n")
        w("**%d roles across %d companies.** Every row carries a verdict and the\n"
          % (len(rows), companies))
        w("reason for it. **%d of the %d verdicts come from a stated eligibility\n"
          % (stated, len(rows)))
        w("field** in the posting rather than from prose, which is the difference\n")
        w("between knowing and guessing.\n\n")

        w("| Verdict | Count | What to do |\n|---|---|---|\n")
        w("| **OPEN** | %d | Apply. No country restriction stated |\n" % len(op))
        w("| **CHECK** | %d | Feed says open to anyone, title names a territory. "
          "Both cannot be true |\n" % len(ch))
        w("| **UNCLEAR** | %d | No eligibility language either way. Open and read |\n"
          % len(un))
        w("| **BLOCKED** | %d | Removed, reason kept against every row |\n\n" % len(bl))

        w("## What came off, and why\n\nThe subtraction is the half worth reading.\n\n")
        w("| Count | Reason |\n|---|---|\n")
        for reason, n in collections.Counter(r["reason"] for r in bl).most_common(10):
            w("| %d | %s |\n" % (n, clean(reason, 90)))

        us = sum(1 for r in bl
                 if "United States" in r["reason"] or "USA" in r["reason"])
        if bl:
            w("\n**%d of the %d removals are United States locks.** That one line\n"
              % (us, len(bl)))
            w("explains why a general remote board feels empty: most of what is on\n")
            w("it is real, and almost none of it is eligible.\n\n")

        for label, group in (("OPEN, apply to these", op),
                             ("CHECK, the feed and the title disagree", ch),
                             ("UNCLEAR, open and read the body", un)):
            w("## %s\n\n" % label)
            if not group:
                w("None.\n\n")
                continue
            w("| Role | Company | Why | Posted | Link |\n|---|---|---|---|---|\n")
            for r in group:
                w("| %s | %s | %s | %s | [open](%s) |\n" % (
                    clean(r["title"], 58), clean(r["company"], 26),
                    clean(r["reason"], 44), r["posted"], r["url"]))
            w("\n")

        w("## The limit\n\n")
        w("A stated eligibility field says who a posting is open to. Nothing more.\n")
        w("It does not say the company pays in dollars, hires outside its own\n")
        w("timezone in practice, or will reply. And an **empty** field means nobody\n")
        w("filled it in, not that the role is global.\n\n")
        w("So this is a filter, not a verdict. Every OPEN row still needs a human\n")
        w("look before anybody applies, and UNCLEAR exists because guessing there\n")
        w("would be dishonest.\n")

    print("wrote %s: OPEN %d, CHECK %d, UNCLEAR %d, BLOCKED %d, %d companies"
          % (dst, len(op), len(ch), len(un), len(bl), companies))


if __name__ == "__main__":
    main()
