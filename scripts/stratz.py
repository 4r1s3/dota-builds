"""Статистика Divine/Immortal пабов из STRATZ (нужен STRATZ_TOKEN)."""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

URL = "https://api.stratz.com/graphql"
BRACKET = "DIVINE_IMMORTAL"

QUERY = """
query($h: Short!, $hs: [Short], $p1: [MatchPlayerPositionType], $p2: [MatchPlayerPositionType],
      $p3: [MatchPlayerPositionType], $p4: [MatchPlayerPositionType], $p5: [MatchPlayerPositionType]) {
  heroStats {
    stats(heroIds: $hs, bracketBasicIds: [%(b)s], groupByPosition: true) { position matchCount winCount }
    %(parts)s
  }
}
"""
PART = """
    i%(n)s: itemFullPurchase(heroId: $h, bracketBasicIds: [%(b)s], positionIds: $p%(n)s) { itemId instance time matchCount winCount }
    s%(n)s: itemStartingPurchase(heroId: $h, bracketBasicIds: [%(b)s], positionIds: $p%(n)s) { itemId instance wasGiven matchCount }
    t%(n)s: talent(heroId: $h, bracketBasicIds: [%(b)s], positionIds: $p%(n)s) { abilityId matchCount winCount }
    m%(n)s: abilityMaxLevel(heroId: $h, bracketBasicIds: [%(b)s], positionIds: $p%(n)s) { abilityId level matchCount }
"""
FULL_QUERY = QUERY % {"b": BRACKET, "parts": "".join(PART % {"n": n, "b": BRACKET} for n in range(1, 6))}


def gql(query, variables, token, tries=5):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for i in range(tries):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {token}", "User-Agent": "STRATZ_API",
            "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
            if d.get("errors"):
                raise RuntimeError(d["errors"][0].get("message"))
            return d["data"]
        except urllib.error.HTTPError as e:
            msg = e.read()[:160].decode("utf-8", "replace")
            print(f"  ! STRATZ: {e.code} {msg} (попытка {i + 1})", file=sys.stderr)
            time.sleep(30 * (i + 1) if e.code in (403, 429) else 5)
        except Exception as e:  # noqa: BLE001
            print(f"  ! STRATZ: {e} (попытка {i + 1})", file=sys.stderr)
            time.sleep(5 * (i + 1))
    return None


def wmedian(pairs):
    """Медиана по парам (значение, вес)."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if not total:
        return None
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def fetch_hero(hid, item_ids, ability_ids, talent_level, is_build_item):
    """Возвращает {pos: {...}} со статистикой Immortal для героя."""
    token = os.environ.get("STRATZ_TOKEN")
    if not token:
        return {}
    v = {"h": hid, "hs": [hid]}
    for n in range(1, 6):
        v[f"p{n}"] = [f"POSITION_{n}"]
    data = gql(FULL_QUERY, v, token)
    if not data:
        return {}
    hs = data["heroStats"]
    totals = {}
    for r in hs.get("stats") or []:
        pos = r.get("position")
        if pos and pos.startswith("POSITION_"):
            n = int(pos[-1])
            totals[n] = (totals.get(n, (0, 0))[0] + r["matchCount"], totals.get(n, (0, 0))[1] + r["winCount"])
    out = {}
    for n in range(1, 6):
        games, wins = totals.get(n, (0, 0))
        if games < 50:
            continue
        # предметы (первая покупка)
        agg = defaultdict(lambda: {"n": 0, "w": 0, "t": []})
        rows = hs.get(f"i{n}") or []
        minutes = rows and max(r["time"] or 0 for r in rows) <= 150
        for r in rows:
            if r["instance"] not in (None, 1):
                continue
            key = item_ids.get(str(r["itemId"]))
            if not key or not is_build_item(key):
                continue
            a = agg[key]
            a["n"] += r["matchCount"]
            a["w"] += r["winCount"]
            t = (r["time"] or 0) * (60 if minutes else 1)
            a["t"].append((t, r["matchCount"]))
        items = []
        for key, a in agg.items():
            share = a["n"] / games
            items.append({"key": key, "share": round(min(share, 1), 2), "time": wmedian(a["t"]),
                          "wr": round(a["w"] / a["n"], 2) if a["n"] else None, "n": a["n"]})
        core = sorted([i for i in items if i["share"] >= 0.4 and i["time"] is not None], key=lambda i: i["time"])
        situational = sorted([i for i in items if 0.1 <= i["share"] < 0.4], key=lambda i: -i["share"])[:10]
        # старт
        best = {}
        for r in hs.get(f"s{n}") or []:
            if r.get("wasGiven"):
                continue
            key = item_ids.get(str(r["itemId"]))
            share = r["matchCount"] / games
            if key and share >= 0.3:
                inst = r["instance"] or 1
                if key not in best or inst > best[key]["count"]:
                    best[key] = {"key": key, "count": inst, "share": round(min(share, 1), 2)}
        start = sorted(best.values(), key=lambda s: -s["share"])
        # «типичный набор»: всё, что берут хотя бы в половине игр, в самом частом количестве
        typical = {}
        for r in hs.get(f"s{n}") or []:
            key = item_ids.get(str(r["itemId"]))
            if key and not r.get("wasGiven") and r["matchCount"] / games >= 0.5:
                typical[key] = max(typical.get(key, 0), r["instance"] or 1)
        start_set = [{"key": k, "count": c} for k, c in typical.items()]
        # таланты
        tal = defaultdict(dict)
        for r in hs.get(f"t{n}") or []:
            name = ability_ids.get(str(r["abilityId"]))
            lvl = talent_level.get(name)
            if lvl:
                tal[lvl][name] = (r["matchCount"], r["winCount"])
        talents = {}
        for lvl, opts in tal.items():
            s = sum(c for c, _ in opts.values()) or 1
            talents[lvl] = {name: {"pick": round(c / s, 2), "wr": round(w / c, 2) if c else None}
                            for name, (c, w) in opts.items()}
        # порядок максимальной прокачки: средний уровень, на котором способность вкачана до конца
        mx = defaultdict(list)
        for r in hs.get(f"m{n}") or []:
            name = ability_ids.get(str(r["abilityId"]))
            if name and not name.startswith("special_bonus") and r["level"]:
                mx[name].append((r["level"], r["matchCount"]))
        max_order = sorted(({"name": k, "level": wmedian(v)} for k, v in mx.items() if wmedian(v)),
                           key=lambda x: x["level"])
        out[n] = {"games": games, "wr": round(wins / games, 2), "core": core,
                  "situational": situational, "start": start, "startSet": start_set, "talents": talents, "maxOrder": max_order}
    return out
