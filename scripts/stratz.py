"""Статистика Divine/Immortal пабов из STRATZ (нужен STRATZ_TOKEN)."""
import json
import re
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

URL = "https://api.stratz.com/graphql"
_WAITED = {"ip": False}
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
            msg = e.read()[:200].decode("utf-8", "replace")
            print(f"  ! STRATZ: {e.code} {msg} (попытка {i + 1})", file=sys.stderr)
            m = re.search(r"frees up in (\d+) minute", msg)
            if e.code == 403 and m and not _WAITED["ip"]:
                # лимит «2 IP за 15 минут»: один раз ждём, пока он освободится, а не сдаёмся
                wait = min(16, int(m.group(1)) + 1) * 60
                print(f"  … жду {wait // 60} мин, пока STRATZ снимет лимит по IP", file=sys.stderr)
                _WAITED["ip"] = True
                time.sleep(wait)
                continue
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


def fetch_hero(hid, item_ids, ability_ids, talent_level, is_build_item, item_costs=None):
    """Возвращает {pos: {...}} со статистикой Immortal для героя."""
    item_costs = item_costs or {}
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
        # не дороже стартовых 600 золота: добавляем по убыванию популярности, пока влезает
        share = {}
        for r in hs.get(f"s{n}") or []:
            key = item_ids.get(str(r["itemId"]))
            if key in typical and (r["instance"] or 1) == typical[key]:
                share[key] = r["matchCount"] / games
        start_set, spent = [], 0
        for k, c in sorted(typical.items(), key=lambda kv: -share.get(kv[0], 0)):
            cost = (item_costs.get(k) or 0) * c
            if spent + cost <= 600:
                start_set.append({"key": k, "count": c})
                spent += cost
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


_WINDAY = None


def _winday(token):
    """Один запрос winDay (все + 5 позиций) на всю сборку: и винрейты, и дневная статистика берутся из него."""
    global _WINDAY
    if _WINDAY is None:
        parts = ['all: winDay(take: 5000, bracketIds: [IMMORTAL], groupBy: HERO_ID) { day heroId winCount matchCount }']
        for n in range(1, 6):
            parts.append(f'p{n}: winDay(take: 5000, bracketIds: [IMMORTAL], positionIds: [POSITION_{n}], groupBy: HERO_ID) '
                         '{ day heroId winCount matchCount }')
        data = gql("{ heroStats { " + " ".join(parts) + " } }", {}, token, tries=5)
        if not data:
            return None
        _WINDAY = data["heroStats"]
    return _WINDAY


def hero_daily(since_day_ts):
    """Победы и игры героев в Immortal по дням, начиная с since_day_ts: для выбора периода на сайте.

    Возвращает {"days": [ts...], "data": {hero: {"all": [[g, w] по дням], 1: [...], ...}}}
    """
    token = os.environ.get("STRATZ_TOKEN")
    if not token:
        return None
    hs = _winday(token)
    if not hs:
        return None
    days = sorted({r["day"] for r in hs.get("all") or [] if (r.get("day") or 0) >= since_day_ts})
    idx = {d: i for i, d in enumerate(days)}
    out = {}
    for key in ["all"] + [f"p{n}" for n in range(1, 6)]:
        k = "all" if key == "all" else str(key[1])
        for r in hs.get(key) or []:
            if r.get("day") not in idx:
                continue
            arr = out.setdefault(r["heroId"], {}).setdefault(k, [[0, 0] for _ in days])
            arr[idx[r["day"]]][0] += r["matchCount"]
            arr[idx[r["day"]]][1] += r["winCount"]
    return {"days": days, "data": out}


def hero_winrates(min_day_ts):
    """Винрейт героев в Immortal по дням (все игры подряд, без перекоса гайдов).

    Возвращает {"all": {hero: [games, wins]}, 1: {...}, ..., 5: {...}, "days": n}
    Берутся только полные дни, начавшиеся не раньше min_day_ts (дни после выхода патча).
    """
    token = os.environ.get("STRATZ_TOKEN")
    if not token:
        return None
    hs = _winday(token)
    if not hs:
        return None
    out, days = {}, set()
    out["trend"] = {}
    for key in ["all"] + [f"p{n}" for n in range(1, 6)]:
        agg, daily = {}, {}
        for r in hs.get(key) or []:
            if (r.get("day") or 0) < min_day_ts:
                continue
            days.add(r["day"])
            g = agg.setdefault(r["heroId"], [0, 0])
            g[0] += r["matchCount"]
            g[1] += r["winCount"]
            d = daily.setdefault(r["day"], {}).setdefault(r["heroId"], [0, 0])
            d[0] += r["matchCount"]
            d[1] += r["winCount"]
        k = "all" if key == "all" else int(key[1])
        out[k] = agg
        out["trend"][k] = _trend(daily)
    out["days"] = len(days)
    return out


def _trend(daily):
    """Последний день против всех предыдущих дней патча: изменение винрейта и популярности (в п.п.)."""
    if len(daily) < 2:
        return {}
    last = max(daily)
    prev = [d for d in daily if d != last]
    m_last = sum(g for g, _ in daily[last].values()) / 10 or 1
    m_prev = sum(g for d in prev for g, _ in daily[d].values()) / 10 or 1
    res = {}
    for h in set(daily[last]) | {h for d in prev for h in daily[d]}:
        gl, wl = daily[last].get(h, [0, 0])
        gp = sum(daily[d].get(h, [0, 0])[0] for d in prev)
        wp = sum(daily[d].get(h, [0, 0])[1] for d in prev)
        if gl < 100 or gp < 100:  # мало игр — изменение будет шумом
            continue
        res[h] = {"wr": round((wl / gl - wp / gp) * 100, 1), "pick": round((gl / m_last - gp / m_prev) * 100, 1),
                  "last": gl}
    return res
