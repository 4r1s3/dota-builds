"""Пабы высокого рейтинга (Immortal) из STRATZ — добор данных, когда про-игр мало.

Берём матчи из подборки STRATZ «guide» по герою и позиции, затем детали матчей
пачками. Возвращаем строки в том же формате, что и про-матчи из OpenDota,
чтобы дальше всё считалось одним кодом. Скачанные матчи кешируются в файл.
"""
import json
import os
import sys
import time
from pathlib import Path

import stratz

CACHE = Path(os.environ.get("PUBS_CACHE", Path(__file__).resolve().parent.parent / ".cache" / "pubs.json"))
MIN_RANK = 80  # 80+ = Immortal (≈7k+ MMR)
MAX_AGE = 21 * 86400

GUIDE_Q = """query($h: Short!, $p: MatchPlayerPositionType!) {
  heroStats { guide(heroId: $h, positionId: $p) { guides { matchId } } } }"""
MATCH_FIELDS = """id startDateTime durationSeconds didRadiantWin rank averageRank radiantNetworthLeads
  players { heroId isRadiant position kills deaths assists goldPerMinute networth
    steamAccount { name seasonRank proSteamAccount { name } }
    abilities { abilityId time level } stats { itemPurchases { time itemId } } }"""


def match_query(ids):
    # запрос matches(ids) у STRATZ только для админов, а одиночные match(id) с алиасами разрешены
    return "{ " + " ".join(f"m{i}: match(id: {int(x)}) {{ {MATCH_FIELDS} }}" for i, x in enumerate(ids)) + " }"


POS = {"POSITION_1": 1, "POSITION_2": 2, "POSITION_3": 3, "POSITION_4": 4, "POSITION_5": 5}


def _load():
    try:
        return json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cache = {k: v for k, v in cache.items() if now - (v.get("start") or 0) < MAX_AGE}
    CACHE.write_text(json.dumps(cache, separators=(",", ":")))


def _pg(arr):
    return "{" + ",".join(str(x) for x in arr) + "}"


def _rows_from_match(m, item_ids):
    """Матч STRATZ -> строки в формате про-матчей OpenDota (purchase_log и abilities как в build.py)."""
    rows = []
    for i, p in enumerate(m.get("players") or []):
        stats = p.get("stats") or {}
        buys = stats.get("itemPurchases") or []
        log = [{"time": b["time"], "key": item_ids.get(str(b["itemId"]))} for b in buys]
        log = [e for e in log if e["key"]]
        abil = sorted(p.get("abilities") or [], key=lambda a: (a.get("time") or 0, a.get("level") or 0))  # порядок прокачки — по времени
        acc = p.get("steamAccount") or {}
        name = ((acc.get("proSteamAccount") or {}).get("name")) or acc.get("name")
        rows.append({
            "match_id": m["id"], "hero_id": p["heroId"],
            "player_slot": (0 if p["isRadiant"] else 128) + (i % 5),
            "pos": POS.get(p.get("position")),
            "kills": p.get("kills"), "deaths": p.get("deaths"), "assists": p.get("assists"),
            "gold_per_min": p.get("goldPerMinute"), "net_worth": p.get("networth"),
            "purchase_log": json.dumps(log), "abilities": _pg(a["abilityId"] for a in abil),
            "radiant_win": m["didRadiantWin"], "start_time": m["startDateTime"],
            "duration": m["durationSeconds"], "gold_adv": _pg(m.get("radiantNetworthLeads") or []),
            "league": "Immortal паб", "pro_name": name, "src": "pub",
            "rank": acc.get("seasonRank") or m.get("rank"),
        })
    return rows


def fetch(wanted, item_ids, budget=450, min_start=0):
    """wanted: список (hero_id, pos), где мало про-игр. Возвращает строки всех игроков найденных матчей."""
    token = os.environ.get("STRATZ_TOKEN")
    if not token or not wanted:
        return []
    cache = _load()
    calls = fails = 0
    need = set()
    for hid, pos in wanted:
        if calls >= budget or fails >= 5:
            break
        d = stratz.gql(GUIDE_Q, {"h": hid, "p": f"POSITION_{pos}"}, token, tries=1)
        calls += 1
        fails = 0 if d else fails + 1
        time.sleep(1.0)
        for g in ((((d or {}).get("heroStats") or {}).get("guide") or [{}])[0] or {}).get("guides") or []:
            if str(g["matchId"]) not in cache:
                need.add(g["matchId"])
    need = sorted(need)
    if fails >= 5:
        print("  ! пабы: подборка матчей STRATZ недоступна, пропускаю", file=sys.stderr)
    print(f"  пабы: {len(wanted)} позиций, новых матчей к загрузке {len(need)}, в кеше {len(cache)}")
    i = fails = 0
    retry = []
    while calls < budget and fails < 6:
        # если пачка упала из-за одного «битого» матча — перезапрашиваем её по одному, потом снова пачками
        if retry:
            batch, is_retry = [retry.pop(0)], True
        elif i < len(need):
            batch, is_retry = need[i:i + 5], False
            i += len(batch)
        else:
            break
        d = stratz.gql(match_query(batch), {}, token, tries=1)
        calls += 1
        time.sleep(1.2)
        if d:
            fails = 0
            for m in d.values():
                if m:
                    cache[str(m["id"])] = {"start": m.get("startDateTime"), "m": m}
        elif not is_retry and len(batch) > 1:
            retry.extend(batch)
        elif not is_retry:
            fails += 1
    _save(cache)
    rows = []
    for v in cache.values():
        if (v.get("start") or 0) >= min_start:  # только матчи текущего патча
            rows.extend(_rows_from_match(v["m"], item_ids))
    print(f"  пабы: загружено {len(rows) // 10} матчей, запросов {calls}", file=sys.stderr)
    return rows
