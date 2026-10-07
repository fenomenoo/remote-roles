# remote-roles

Pulls remote go-to-market roles from six public job feeds and sorts them by
whether a candidate outside the US, UK and EU can actually take them.

No API keys. No accounts. Standard library only.

    python pull_roles.py --days 45 --pages 300 --out roles

## The problem it solves

Aggregators label a job "worldwide" and mean the United States. Checked by hand
on 6 October 2026, **four of five "work from anywhere" listings turned out to be
country-locked** once the posting itself was opened. Sourcegraph advertised
anywhere in the world and required Austin, Chicago, Denver or Seattle.

So the work is not finding postings. It is deciding which ones are real, and
being able to show why.

## What it does

Six feeds, pulled in one pass:

| Feed | Postings | Eligibility data |
|---|---|---|
| himalayas.app | ~6,000 per run, 115k available | **`locationRestrictions`, a structured list** |
| weworkremotely.com (RSS) | ~130 | **`<region>`, e.g. "Anywhere in the World"** |
| arbeitnow.com | ~300 | prose only |
| remoteok.com | ~99 | prose only |
| jobicy.com | ~200 | prose only |
| remotive.com | ~17 | prose only |

Two of the six state eligibility as a field rather than prose. Those verdicts
are marked `stated` and are worth more than the ones read out of body text,
which are marked `prose`. The distinction is in the output, because a verdict
is only as good as where it came from.

Every row is then given one of four verdicts:

- **OPEN** — no country restriction stated
- **CHECK** — the feed says open to anyone, but the title names a territory.
  Both cannot be true, so it goes in its own column instead of being counted
  as a win
- **UNCLEAR** — no eligibility language either way
- **BLOCKED** — country-locked, with the lock quoted against the row

## A run from 7 October 2026

**595 roles, 435 companies**, 546 verdicts from a stated field.

    OPEN       59
    CHECK      13
    UNCLEAR    19
    BLOCKED   504

**304 of the 504 removals are United States locks.** That single number is why
a general remote board feels like it holds nothing: most of it is real, and
almost none of it is for this candidate.

## Titles

Searching "SDR" misses most of this work. Reliance Health published exactly this
job as **Sales Excellence Associate**. The title pattern covers sales
development, BDR, business development, lead generation, lead qualification,
demand generation, GTM, growth, revenue and sales operations, sales excellence,
partnerships, market expansion, outbound, pipeline development, account
executive and manager, commercial roles, prospecting and appointment setting.

`--all-titles` drops the filter entirely.

## The limit

**A stated eligibility field says who a posting is open to. Nothing more.**

It does not say the company pays in dollars, that it hires outside its own
timezone in practice, or that anyone will reply. An **empty** restrictions field
means nobody filled the field in, not that the role is global.

So this is a filter, not a verdict. Every OPEN row still needs a human look
before anybody applies, and the UNCLEAR column exists because guessing there
would be dishonest.

## Known soft spots

- Himalayas ignores every filter parameter tried, so depth is the only way
  through at 20 postings a page. `--pages` controls it.
- Arbeitnow rate limits at speed; the client backs off and retries three times.
- Most We Work Remotely category feeds 301 away. Two serve.
- `CHECK` is a title heuristic. A role called "Account Executive, Enterprise"
  can still be territory-bound without saying so.
