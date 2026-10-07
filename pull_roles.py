#!/usr/bin/env python3
"""Pull remote GTM roles from five public job feeds and sort them by whether a
Nigeria-based candidate can actually take them.

No API keys. No accounts. Standard library only.

The pulling is the easy half. The point is the subtraction: aggregators tag a
job "worldwide" when they mean the United States, so every row is classified
against the eligibility data in the posting itself and the ones that fail are
written out with the reason attached rather than silently dropped.

Two of the five feeds state eligibility as a structured field rather than prose,
and those verdicts are worth more than the rest:

  * himalayas  -> locationRestrictions, a list of countries
  * weworkremotely -> <region>, e.g. "Anywhere in the World"

Everything else is read out of the body text, which is weaker and is marked so.

    python pull_roles.py
    python pull_roles.py --days 30 --out mylist --all-titles
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (remote-roles; public job feeds)"}

# Himalayas serves 20 per page. This is how deep to go before stopping.
HIMALAYAS_PAGES = 300

# The work, under every name it gets published as. Searching "SDR" alone misses
# most of it: Reliance Health called this exact job "Sales Excellence Associate".
TITLE_PAT = re.compile(
    r"sales\s*development|\bsdr\b|\bbdr\b|business\s*development"
    r"|lead\s*gen|lead\s*qualif|demand\s*gen|\bgtm\b|go.to.market"
    r"|growth\s*(associate|manager|lead|marketer|specialist|engineer|hacker)"
    r"|revenue\s*oper|sales\s*oper|sales\s*excellence|\brevops\b"
    r"|partnership|market\s*expansion|outbound|pipeline\s*development"
    r"|account\s*executive|account\s*manager|commercial\s*(associate|analyst|manager)"
    r"|prospect|appointment\s*setter|sales\s*(associate|specialist|executive)",
    re.I,
)

# A country lock written in prose. Kills the row.
BLOCK_PAT = re.compile(
    r"\b(u\.?s\.?a?|united\s+states|usa)\s*(only|-?based|\s+residents?)"
    r"|only\s+(in\s+)?(the\s+)?(u\.?s\.?|united\s+states|usa|canada|uk|india|australia)"
    r"|must\s+(be\s+)?(located|based|reside|live)\s+in\s+(the\s+)?"
    r"(u\.?s|united\s+states|usa|canada|uk|australia|india|germany|france|spain"
    r"|poland|portugal|singapore|brazil|mexico|philippines)"
    r"|authoriz\w*\s+to\s+work\s+in\s+the\s+(u\.?s|united\s+states)"
    r"|work\s+authoriz\w*\s+in\s+the\s+(u\.?s|united\s+states)"
    r"|eligible\s+to\s+work\s+in\s+(the\s+)?(u\.?s|united\s+states|uk|canada)"
    r"|requires?\s+.{0,20}\b(visa|green\s*card)"
    r"|commute\s+to\s+(our|the)\s+office",
    re.I,
)

# Language that means he can actually take it. EMEA counts: the A is Africa.
OPEN_PAT = re.compile(
    r"worldwide|anywhere\s+in\s+the\s+world|work\s+from\s+anywhere"
    r"|globally\s+distributed|fully\s+(remote|distributed)"
    r"|\bemea\b|africa|nigeria"
    r"|employer\s+of\s+record|\beor\b|through\s+deel"
    r"|\boyster\b|contractor\s+of\s+record",
    re.I,
)

# A location string naming one country that is not his. Soft kill.
GEO_LOCK = re.compile(
    r"\b(usa|u\.s\.|united\s+states|canada|united\s+kingdom|australia"
    r"|india|germany|france|spain|poland|portugal|netherlands|ireland"
    r"|singapore|brazil|mexico|argentina|colombia|philippines|japan)\b",
    re.I,
)

# A role whose TITLE names a territory, while the feed calls it open to anyone.
# Both things cannot be true. The feed is describing the company's hiring policy;
# the title is describing the patch. Flag it rather than counting it as a win.
TITLE_GEO = re.compile(
    r"\b(france|germany|spain|italy|nordics?|denmark|sweden|norway"
    r"|benelux|poland|portugal|netherlands|dutch|german|french|spanish"
    r"|italian|latam|apac|anz|japan|korea|india|brazil|mexico|canada"
    r"|chicago|san\s+francisco|norcal|socal|new\s+york|nyc|boston"
    r"|austin|seattle|denver|atlanta|miami|london|dublin|berlin|paris"
    r"|madrid|riyadh|dubai|uae|saudi|singapore|sydney|toronto"
    r"|midwest|northeast|southeast)\b",
    re.I,
)

# Structured eligibility values that still mean yes.
# "South Africa" contains "Africa" and is not an open region. The lookbehind
# is the whole reason this is not a one-word match.
OK_REGION = re.compile(
    r"anywhere|worldwide|global|emea|(?<!south\s)africa|nigeria",
    re.I,
)


def fetch(url, timeout=60, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data.decode("utf-8", "replace"))


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def epoch(v):
    """Every feed dates its postings differently. Normalise or admit defeat."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace("Z", "+00:00")
    if s.isdigit():
        return int(s)
    try:
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp())
    except Exception:
        pass
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
              "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            d = datetime.strptime(s, f)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return int(d.timestamp())
        except Exception:
            pass
    return 0


def collect(verbose=True):
    global HIMALAYAS_PAGES
    out = []

    def add(src, title, company, loc, url, when, body, salary="", hard=None):
        out.append({
            "source": src,
            "title": (title or "").strip(),
            "company": (company or "").strip(),
            "location": strip_html(loc)[:120],
            "url": url or "",
            "epoch": epoch(when),
            "body": strip_html(body)[:4000],
            "salary": salary,
            # hard is the structured eligibility list, or None if the feed has none
            "hard": hard,
        })

    def note(name, n):
        if verbose:
            print("  %-14s %5d" % (name, n))

    # 1. Himalayas. The only feed that states eligibility as structured data.
    # It holds ~115k postings, ignores every filter parameter anyone has tried,
    # and serves 20 per page, so the only way through is the cursor.
    n = 0
    try:
        cursor, pages = None, 0
        while pages < HIMALAYAS_PAGES:
            u = "https://himalayas.app/jobs/api?limit=100"
            if cursor:
                u += "&cursor=" + cursor
            d = fetch(u)
            rows = d.get("jobs", [])
            if not rows:
                break
            for j in rows:
                sal = ""
                if j.get("minSalary") and j.get("maxSalary"):
                    sal = "%s-%s %s" % (j["minSalary"], j["maxSalary"],
                                        j.get("currency") or "")
                add("himalayas", j.get("title"), j.get("companyName"),
                    ", ".join(j.get("locationRestrictions") or []) or "no restriction",
                    j.get("applicationLink"), j.get("pubDate"),
                    (j.get("excerpt") or "") + " " + (j.get("description") or ""),
                    sal.strip(), j.get("locationRestrictions") or [])
                n += 1
            cursor = d.get("nextCursor")
            if not cursor:
                break
            pages += 1
            if pages % 50 == 0 and verbose:
                print("    himalayas ... %d" % n)
            time.sleep(0.15)
    except Exception as e:
        print("  himalayas stopped after %d: %s" % (n, e), file=sys.stderr)
    note("himalayas", n)

    # 2. We Work Remotely RSS. Carries a <region> field.
    # Most of their other category feeds 301 away; these are the ones that serve.
    n = 0
    for feed in ("remote-sales-and-marketing-jobs", "remote-customer-support-jobs"):
        try:
            xml = fetch("https://weworkremotely.com/categories/%s.rss" % feed, raw=True)
            root = ET.fromstring(xml)
            for it in root.iter("item"):
                def t(tag):
                    e = it.find(tag)
                    return e.text if e is not None and e.text else ""
                title = t("title")
                company, _, role = title.partition(":")
                region = t("region")
                add("weworkremotely", role.strip() or title, company.strip(),
                    region, t("link"), t("pubDate"), t("description"),
                    "", [region] if region else [])
                n += 1
        except Exception as e:
            print("  wwr %s failed: %s" % (feed, e), file=sys.stderr)
    note("weworkremotely", n)

    # 3. Arbeitnow. The volume source, and it rate limits hard at speed.
    n = 0
    page, misses = 1, 0
    while page <= 60 and misses < 3:
        try:
            d = fetch("https://www.arbeitnow.com/api/job-board-api?page=%d" % page)
        except Exception as e:
            misses += 1
            if verbose:
                print("    arbeitnow page %d: %s, backing off" % (page, e))
            time.sleep(5)
            continue
        rows = d.get("data", [])
        if not rows:
            break
        for j in rows:
            if not j.get("remote"):
                continue
            add("arbeitnow", j.get("title"), j.get("company_name"),
                j.get("location"), j.get("url"), j.get("created_at"),
                j.get("description"))
            n += 1
        page += 1
        time.sleep(1.1)
    note("arbeitnow", n)

    # 4. RemoteOK. Only serves the most recent ~100.
    n = 0
    try:
        for j in fetch("https://remoteok.com/api")[1:]:
            sal = ""
            if j.get("salary_min"):
                sal = "%s-%s USD" % (j.get("salary_min"), j.get("salary_max"))
            add("remoteok", j.get("position"), j.get("company"), j.get("location"),
                j.get("url"), j.get("epoch") or j.get("date"),
                j.get("description"), sal)
            n += 1
    except Exception as e:
        print("  remoteok failed:", e, file=sys.stderr)
    note("remoteok", n)

    # 5. Jobicy, by tag. The industry parameter 400s, tags work.
    n = 0
    for tag in ("sales", "marketing", "business", "management"):
        try:
            d = fetch("https://jobicy.com/api/v2/remote-jobs?count=50&tag=%s" % tag)
            for j in d.get("jobs", []):
                add("jobicy", j.get("jobTitle"), j.get("companyName"),
                    j.get("jobGeo"), j.get("url"), j.get("pubDate"),
                    j.get("jobExcerpt") or j.get("jobDescription"))
                n += 1
            time.sleep(0.2)
        except Exception as e:
            print("  jobicy %s failed: %s" % (tag, e), file=sys.stderr)
    note("jobicy", n)

    # 6. Remotive. Small now, but free and sometimes unique.
    n = 0
    try:
        for j in fetch("https://remotive.com/api/remote-jobs").get("jobs", []):
            add("remotive", j.get("title"), j.get("company_name"),
                j.get("candidate_required_location"), j.get("url"),
                j.get("publication_date"), j.get("description"),
                j.get("salary") or "")
            n += 1
    except Exception as e:
        print("  remotive failed:", e, file=sys.stderr)
    note("remotive", n)

    return out


def classify(r):
    """Return (verdict, confidence, reason).

    A structured eligibility field beats anything read out of prose, so it is
    checked first and marked as the stronger verdict.
    """
    hard = r.get("hard")
    if hard is not None and len(hard) > 0:
        joined = ", ".join(hard)
        if OK_REGION.search(joined):
            if TITLE_GEO.search(r["title"]):
                return ("CHECK", "stated",
                        "feed says %s but the title names a territory"
                        % joined[:40])
            return "OPEN", "stated", "eligibility field: %s" % joined[:70]
        return "BLOCKED", "stated", "eligibility field: %s" % joined[:70]
    if hard is not None and len(hard) == 0:
        if TITLE_GEO.search(r["title"]):
            return ("CHECK", "stated",
                    "no stated restriction but the title names a territory")
        return "OPEN", "stated", "eligibility field is empty, no country restriction"

    hay = r["location"] + " \n " + r["body"]

    m = BLOCK_PAT.search(hay)
    if m:
        return "BLOCKED", "prose", "body says: %s" % m.group(0).strip().lower()[:60]

    m = OPEN_PAT.search(hay)
    if m:
        return "OPEN", "prose", "body says: %s" % m.group(0).strip().lower()[:60]

    if r["location"] and GEO_LOCK.search(r["location"]):
        return "BLOCKED", "prose", "location is country-locked: %s" % r["location"][:50]

    return "UNCLEAR", "none", "no eligibility language either way, open and read"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45, help="max age of posting")
    ap.add_argument("--out", default="roles")
    ap.add_argument("--all-titles", action="store_true",
                    help="skip the GTM title filter")
    ap.add_argument("--pages", type=int, default=300,
                    help="how many Himalayas pages (20 postings each)")
    a = ap.parse_args()

    global HIMALAYAS_PAGES
    HIMALAYAS_PAGES = a.pages

    print("pulling...")
    rows = collect()
    print("  %-14s %5d raw" % ("TOTAL", len(rows)))

    cutoff = time.time() - a.days * 86400
    seen, kept = set(), []
    for r in rows:
        if not r["title"] or not r["company"]:
            continue
        if not a.all_titles and not TITLE_PAT.search(r["title"]):
            continue
        if r["epoch"] and r["epoch"] < cutoff:
            continue
        key = (r["company"].lower(), re.sub(r"\W+", "", r["title"].lower()))
        if key in seen:
            continue
        seen.add(key)
        r["verdict"], r["confidence"], r["reason"] = classify(r)
        r["posted"] = (datetime.fromtimestamp(r["epoch"], timezone.utc).strftime("%Y-%m-%d")
                       if r["epoch"] else "")
        kept.append(r)

    order = {"OPEN": 0, "CHECK": 1, "UNCLEAR": 2, "BLOCKED": 3}
    conf = {"stated": 0, "prose": 1, "none": 2}
    kept.sort(key=lambda r: (order[r["verdict"]], conf[r["confidence"]], -r["epoch"]))

    cols = ["verdict", "confidence", "reason", "title", "company", "location",
            "salary", "posted", "source", "url"]
    with open(a.out + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(kept)

    n = {k: sum(1 for r in kept if r["verdict"] == k) for k in order}
    stated = sum(1 for r in kept if r["confidence"] == "stated")
    print("\n%d roles after the title filter, %d companies" % (
        len(kept), len({r["company"].lower() for r in kept})))
    print("  OPEN     %4d   apply to these" % n["OPEN"])
    print("  CHECK    %4d   open to anyone, but the title names a territory"
          % n["CHECK"])
    print("  UNCLEAR  %4d   open and read the body" % n["UNCLEAR"])
    print("  BLOCKED  %4d   removed, reason kept in the file" % n["BLOCKED"])
    print("  (%d of all verdicts come from a stated eligibility field,"
          " the rest from prose)" % stated)
    print("\nwrote %s.csv" % a.out)


if __name__ == "__main__":
    main()
