"""Непредвзятый набор Immortal-матчей: все рейтинговые игры топ-игроков лидерборда (победы и поражения подряд).

В отличие от «гайдов» STRATZ (там только выигранные игры героя), здесь берётся вся история игрока,
поэтому по этим матчам можно честно считать винрейты, стадии драфта и соло/пати.

Стадии рейтингового All Pick: обе команды пикают одновременно —
стадия 1: по 2 героя вслепую; стадия 2: ещё по 2, видны 2 героя врага; стадия 3 (ласт-пик): по 1, видны 4 героя врага.
"""
import json
import os
import sys
import time
from pathlib import Path

import stratz

CACHE = Path(os.environ.get("LADDER_CACHE", Path(__file__).resolve().parent.parent / ".cache" / "ladder.json"))
DIVISIONS = ["EUROPE", "AMERICAS", "SE_ASIA", "CHINA"]
RANKED, ALL_PICK_RANKED = 7, 22
MAX_AGE = 30 * 86400

MATCH_FIELDS = """id startDateTime durationSeconds didRadiantWin rank radiantNetworthLeads lobbyType gameMode
  pickBans { heroId order isPick isRadiant }
  players { heroId isRadiant position partyId kills deaths assists goldPerMinute networth
    steamAccountId steamAccount { name seasonLeaderboardRank }
    abilities { abilityId time } stats { itemPurchases { time itemId } } }"""


def _load():
    try:
        return json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {"players": {}, "matches": {}}


def _save(c):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    c["matches"] = {k: v for k, v in c["matches"].items() if now - v["start"] < MAX_AGE}
    CACHE.write_text(json.dumps(c, separators=(",", ":")))


def _stages(pick_bans):
    """heroId -> стадия пика (1, 2, 3) по порядку пиков каждой команды."""
    out = {}
    picks = sorted((p for p in pick_bans or [] if p.get("isPick") and p.get("heroId")), key=lambda p: p["order"])
    for side in (True, False):
        mine = [p for p in picks if p["isRadiant"] == side]
        for i, p in enumerate(mine):
            out[p["heroId"]] = 1 if i < 2 else 2 if i < 4 else 3
    return out


def _compact(m):
    stages = _stages(m.get("pickBans"))
    ps = []
    for p in m.get("players") or []:
        acc = p.get("steamAccount") or {}
        ps.append({
            "h": p["heroId"], "r": p["isRadiant"], "pos": p.get("position"), "party": p.get("partyId"),
            "k": p.get("kills"), "d": p.get("deaths"), "a": p.get("assists"), "gpm": p.get("goldPerMinute"),
            "nw": p.get("networth"), "acc": p.get("steamAccountId"), "name": acc.get("name"),
            "lb": acc.get("seasonLeaderboardRank"), "st": stages.get(p["heroId"]),
            "ab": [a["abilityId"] for a in sorted(p.get("abilities") or [], key=lambda a: a.get("time") or 0)],
            "buy": [[b["time"], b["itemId"]] for b in ((p.get("stats") or {}).get("itemPurchases") or [])],
        })
    return {"start": m["startDateTime"], "dur": m["durationSeconds"], "rw": m["didRadiantWin"],
            "rank": m.get("rank"), "adv": m.get("radiantNetworthLeads") or [], "p": ps}


def fetch(min_start, budget=340, top=1500, per_player=20):
    """Докачивает новые рейтинговые матчи топ-игроков и возвращает весь кеш матчей {id: compact}."""
    token = os.environ.get("STRATZ_TOKEN")
    cache = _load()
    if not token:
        return cache["matches"]
    calls = 0
    # 1) топ лидерборда по регионам
    accounts = {}
    # у самого топа (~8500+ MMR) рейтинговые игры — Immortal Draft, они закрыты; поэтому берём места пошире
    for div in DIVISIONS:
        for skip in range(0, top, 300):
            q = (f'{{ leaderboard {{ season(request: {{ leaderBoardDivision: {div} }}) '
                 f'{{ players(take: 300, skip: {skip}) {{ steamAccountId rank }} }} }} }}')
            d = stratz.gql(q, {}, token, tries=2)
            calls += 1
            time.sleep(1.0)
            for p in (((d or {}).get("leaderboard") or {}).get("season") or {}).get("players") or []:
                accounts[str(p["steamAccountId"])] = (div, p["rank"])
    # 2) история: сначала те, кого давно не проверяли
    order = sorted(accounts, key=lambda a: cache["players"].get(a, 0))
    from collections import Counter
    kinds = Counter()
    new, fails, i = 0, 0, 0
    while i < len(order) and calls < budget and fails < 6:
        batch = order[i:i + 3]
        i += len(batch)
        parts = []
        for j, acc in enumerate(batch):
            since = max(int(min_start), int(cache["players"].get(acc, 0)) - 3600)
            # фильтруем по типу игры сами: у топ-игроков много скримов (Captain's Mode в лобби)
            parts.append(f'p{j}: player(steamAccountId: {acc}) {{ matches(request: {{ take: {per_player}, '
                         f'startDateTime: {since} }}) {{ {MATCH_FIELDS} }} }}')
        d = stratz.gql("{ " + " ".join(parts) + " }", {}, token, tries=1)
        calls += 1
        time.sleep(1.2)
        if not d:
            fails += 1
            continue
        fails = 0
        now = int(time.time())
        for j, acc in enumerate(batch):
            cache["players"][acc] = now
            for m in ((d.get(f"p{j}") or {}).get("matches") or []):
                if not m:
                    continue
                kinds[(m.get("lobbyType"), m.get("gameMode"))] += 1
                if m.get("lobbyType") != "RANKED" or m.get("gameMode") != "ALL_PICK_RANKED":
                    continue
                if str(m["id"]) not in cache["matches"] and m.get("startDateTime", 0) >= min_start:
                    cache["matches"][str(m["id"])] = _compact(m)
                    new += 1
    _save(cache)
    print(f"  лидерборд: {len(accounts)} игроков, новых матчей {new}, всего в кеше {len(cache['matches'])}, "
          f"запросов {calls}; типы игр: {kinds.most_common(5)}", file=sys.stderr)
    return cache["matches"]


def summary(matches, hero_names, min_games=40):
    """Короткая сводка для лога: соло/пати и стадии драфта (пока без вывода на сайт)."""
    from collections import defaultdict
    n = len(matches)
    if not n:
        return "лидерборд: матчей пока нет"
    solo_matches = sum(1 for m in matches.values() if all(p["party"] is None for p in m["p"]))
    solo_players = sum(1 for m in matches.values() for p in m["p"] if p["party"] is None)
    stage = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # stage -> hero -> [games, wins]
    total = defaultdict(int)
    for m in matches.values():
        for p in m["p"]:
            if not p["st"]:
                continue
            won = p["r"] == m["rw"]
            stage[p["st"]][p["h"]][0] += 1
            stage[p["st"]][p["h"]][1] += won
            total[p["st"]] += 1
    lines = [f"лидерборд: {n} матчей, полностью соло {solo_matches / n:.0%}, игроков соло {solo_players / (n * 10):.0%}"]
    names = {1: "стадия 1 (вслепую)", 2: "стадия 2", 3: "ласт-пик"}
    for st in (1, 2, 3):
        hs = stage[st]
        often = sorted(hs.items(), key=lambda kv: -kv[1][0])[:8]
        good = sorted([kv for kv in hs.items() if kv[1][0] >= min_games], key=lambda kv: -kv[1][1] / kv[1][0])[:8]
        lines.append(f"{names[st]}: чаще всего — " + ", ".join(
            f"{hero_names.get(h, h)} {g / max(1, total[st]) * 2:.0%}" for h, (g, w) in often))
        lines.append(f"{names[st]}: лучший винрейт (≥{min_games} игр) — " + ", ".join(
            f"{hero_names.get(h, h)} {w / g:.0%} ({g})" for h, (g, w) in good))
    return "\n".join(lines)


def solo_stats(matches):
    """Статистика героев: все матчи набора и только матчи, где все 10 игроков играли соло."""
    from collections import defaultdict
    POS = {"POSITION_1": "1", "POSITION_2": "2", "POSITION_3": "3", "POSITION_4": "4", "POSITION_5": "5"}
    out = defaultdict(lambda: {"all": defaultdict(lambda: [0, 0]), "solo": defaultdict(lambda: [0, 0])})
    n = n_solo = 0
    for m in matches.values():
        solo = all(p["party"] is None for p in m["p"])
        n += 1
        n_solo += solo
        for p in m["p"]:
            won = int(p["r"] == m["rw"])
            for key in ("a", POS.get(p.get("pos"))):
                if not key:
                    continue
                out[p["h"]]["all"][key][0] += 1
                out[p["h"]]["all"][key][1] += won
                if solo:
                    out[p["h"]]["solo"][key][0] += 1
                    out[p["h"]]["solo"][key][1] += won
    return {"matches": n, "solo": n_solo,
            "heroes": {h: {"all": dict(v["all"]), "solo": dict(v["solo"])} for h, v in out.items()}}


def to_rows(matches, item_ids, min_start=0):
    """Матчи лидерборда -> строки в формате build.py (как пабы), с пометкой lad: по ним честно считать винрейты."""
    import json as _json
    pos_map = {f"POSITION_{n}": n for n in range(1, 6)}
    rows = []
    for mid, m in matches.items():
        if m.get("start", 0) < min_start:
            continue
        slot = {True: 0, False: 128}
        for p in m.get("p") or []:
            s = slot[bool(p["r"])]
            slot[bool(p["r"])] += 1
            log = [{"time": t, "key": item_ids.get(str(i))} for t, i in p.get("buy") or []]
            log = [e for e in log if e["key"]]
            rows.append({
                "match_id": int(mid), "hero_id": p["h"], "player_slot": s, "pos": pos_map.get(p.get("pos")),
                "kills": p.get("k"), "deaths": p.get("d"), "assists": p.get("a"),
                "gold_per_min": p.get("gpm"), "net_worth": p.get("nw"),
                "purchase_log": _json.dumps(log), "abilities": "{" + ",".join(str(a) for a in p.get("ab") or []) + "}",
                "radiant_win": m["rw"], "start_time": m["start"], "duration": m["dur"],
                "gold_adv": "{" + ",".join(str(x) for x in m.get("adv") or []) + "}",
                "league": "Immortal паб", "pro_name": p.get("name"), "src": "pub", "lad": True,
                "rank": m.get("rank"), "match_rank": m.get("rank"), "lb": p.get("lb"),
            })
    return rows
