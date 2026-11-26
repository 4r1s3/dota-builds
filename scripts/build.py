#!/usr/bin/env python3
"""Собирает актуальные билды по про-матчам из OpenDota и пишет site/data/*.json.

Запуск: python scripts/build.py [--days 30]
Без ключей. Если задан OPENDOTA_API_KEY, он добавляется к запросам.
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ladder  # noqa: E402
import pubs  # noqa: E402
import valve  # noqa: E402
import reasons  # noqa: E402
import stratz  # noqa: E402

API = "https://api.opendota.com/api"
CDN = "https://cdn.cloudflare.steamstatic.com"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

# Расходники и прочее, что не показываем среди «предметов билда»
CONSUMABLES = {
    "tango", "tango_single", "flask", "clarity", "ward_observer", "ward_sentry",
    "ward_dispenser", "smoke_of_deceit", "dust", "tpscroll", "enchanted_mango",
    "faerie_fire", "blood_grenade", "tome_of_knowledge", "famango", "great_famango",
    "greater_famango", "cheese", "aghanims_shard_roshan", "ultimate_scepter_roshan",
    "refresher_shard", "aegis", "royal_jelly", "river_painter", "branches",
}
# Предметы без рецепта, которые всё же стоит показывать как часть билда
STANDALONE_OK = {"blink", "boots", "magic_stick", "aghanims_shard", "infused_raindrop",
                 "orb_of_venom", "quelling_blade", "wind_lace", "javelin", "gem"}

PUB_MIN = 8            # если про-игр на позиции меньше — добираем Immortal-пабы
STOMP_ADV = 10000      # перевес команды по золоту, после которого игра «шла очень хорошо»
STOMP_MINUTE = 25      # ...если он набран к этой минуте
STOMP_GPM_RATIO = 1.25 # или GPM игрока выше медианы героя на позиции на 25%
HARD_ADV = -10000      # обратная ситуация — игра шла тяжело


def get(path, params=None, tries=4):
    params = dict(params or {})
    key = os.environ.get("OPENDOTA_API_KEY")
    if key:
        params["api_key"] = key
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dota-builds/1.0 (+github.com/4r1s3/dota-builds)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {path}: {e} (попытка {i + 1})", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"не удалось получить {path}")


def explorer(sql):
    d = get("explorer", {"sql": sql})
    if d.get("err"):
        raise RuntimeError(d["err"])
    return d["rows"]


AU_SQL = None


def _au_sql():
    """Колонка с инвентарём медведя Lone Druid; если в OpenDota её нет — работаем без неё."""
    global AU_SQL
    if AU_SQL is None:
        try:
            explorer("SELECT to_json(additional_units)::text AS au FROM player_matches WHERE hero_id = 80 "
                     "AND additional_units IS NOT NULL LIMIT 1")
            AU_SQL = "\n               CASE WHEN pm.hero_id = 80 THEN to_json(pm.additional_units)::text END AS additional_units,"
        except Exception as e:
            print(f"  ! additional_units недоступна: {e}")
            AU_SQL = ""
    return AU_SQL


def bear_from_au(text, item_by_id):
    """additional_units OpenDota -> ключи предметов медведя (или None, если данных нет)."""
    if not text:
        return None
    try:
        units = json.loads(text)
    except ValueError:
        return None
    if isinstance(units, dict):
        units = [units]
    for u in units or []:
        if isinstance(u, str):
            try:
                u = json.loads(u)
            except ValueError:
                continue
        if not isinstance(u, dict) or "bear" not in str(u.get("unitname", "bear")):
            continue
        ids = [u.get(f) for f in ("item_0", "item_1", "item_2", "item_3", "item_4", "item_5",
                                   "backpack_0", "backpack_1", "backpack_2")]
        return [k for k in (item_by_id.get(str(i)) for i in ids if i) if k]
    return None


def fetch_rows(days, min_start=0):
    AU = _au_sql()
    now = int(time.time())
    rows = []
    chunk = 5
    for start in range(days, 0, -chunk):
        t0 = max(now - start * 86400, int(min_start))  # только матчи текущего патча
        t1 = now - max(start - chunk, 0) * 86400
        if t1 <= t0:
            continue
        sql = f"""
        SELECT pm.match_id, pm.hero_id, pm.account_id, pm.player_slot, pm.lane_role,
               pm.kills, pm.deaths, pm.assists, pm.gold_per_min, pm.net_worth,
               pm.purchase_log::text AS purchase_log,
               pm.ability_upgrades_arr::text AS abilities,{AU}
               m.radiant_win, m.start_time, m.duration,
               m.radiant_gold_adv::text AS gold_adv,
               l.name AS league, np.name AS pro_name, np.team_name AS team
        FROM player_matches pm
        JOIN matches m USING(match_id)
        LEFT JOIN leagues l USING(leagueid)
        LEFT JOIN notable_players np ON np.account_id = pm.account_id
        WHERE m.start_time >= {t0} AND m.start_time < {t1}
        """
        part = explorer(sql)
        print(f"  {start}..{max(start - chunk, 0)} дней назад: {len(part)} строк")
        rows.extend(part)
        time.sleep(1.5)
    return rows


def pg_array(text):
    """'{1,2,3}' -> [1,2,3]; поддерживает массив JSON-строк purchase_log."""
    if not text or text in ("{}", "NULL", "[]"):
        return []
    if text.startswith("["):
        return json.loads(text)
    if text.startswith("{\"{") or text.startswith("{\"\\"):
        # массив json-объектов в синтаксисе postgres
        inner = text[1:-1]
        out, buf, in_q, esc = [], [], False, False
        for ch in inner:
            if in_q:
                if esc:
                    buf.append(ch)
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_q = False
                else:
                    buf.append(ch)
            elif ch == '"':
                in_q = True
            elif ch == ",":
                out.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        if buf:
            out.append("".join(buf))
        return [json.loads(x) for x in out if x]
    return [int(x) if x.lstrip("-").isdigit() else x for x in text[1:-1].split(",") if x != "NULL"]


def assign_positions(players):
    """players: строки одной команды. Возвращает {account/hero: pos 1..5}."""
    pos = {}
    by_nw = sorted(players, key=lambda p: -(p["net_worth"] or 0))
    lanes = defaultdict(list)
    for p in by_nw:
        lanes[p["lane_role"]].append(p)
    taken = set()

    def put(p, n):
        if p["hero_id"] not in pos and n not in taken:
            pos[p["hero_id"]] = n
            taken.add(n)

    if lanes.get(2):
        put(lanes[2][0], 2)
    if lanes.get(1):
        put(lanes[1][0], 1)
    if lanes.get(3):
        put(lanes[3][0], 3)
    for p in lanes.get(1, [])[1:]:
        put(p, 5)
    for p in lanes.get(3, [])[1:]:
        put(p, 4)
    rest = [n for n in (1, 2, 3, 4, 5) if n not in taken]
    for p in by_nw:
        if p["hero_id"] not in pos and rest:
            n = rest.pop(0)
            pos[p["hero_id"]] = n
            taken.add(n)
    return pos


def median(xs):
    return int(statistics.median(xs)) if xs else None


def greedy_sequence(seqs, length, talent_levels):
    """Самый частый билд, но всегда «легальный».

    ability_upgrades_arr — порядок очков, а не уровни героя (на 17, 19, 21–24 очков нет).
    Ограничения берём из самих игр: максимум очков в способность и самый ранний номер
    очка, на котором встречалось k-е вложение (так учитываются ульты и способности с 5 уровнями).
    """
    seqs = [s[:length] for s in seqs if s]
    cap, gate = Counter(), {}
    for s in seqs:
        seen = Counter()
        for i, a in enumerate(s):
            seen[a] += 1
            key = (a, seen[a])
            gate[key] = min(gate.get(key, 99), i)
        for a, c in seen.items():
            cap[a] = max(cap[a], c)

    out, have, tiers = [], Counter(), set()

    def tier_of(a):
        if not a.startswith("special_bonus"):
            return None
        if a in talent_levels:
            return talent_levels[a]
        g = gate.get((a, 1), 99)  # талант не из справочника — уровень по самому раннему очку
        return 1 if g < 14 else 2 if g < 17 else 3 if g < 18 else 4

    # самое раннее очко (индекс с 0), на котором доступен талант: 10-й ур. — 10-е очко, 15-й — 16-е, 20-й — 18-е, 25-й — 19-е
    tier_min = {1: 9, 2: 15, 3: 17, 4: 18}

    def ok(a, idx):
        if have[a] >= cap[a] or gate.get((a, have[a] + 1), 99) > idx:
            return False
        tier = tier_of(a)
        if tier and idx < tier_min[tier]:
            return False
        return not (tier and tier in tiers)

    for idx in range(length):
        pool = [s for s in seqs if len(s) > idx and s[:idx] == out]
        if len(pool) < 3:
            pool = [s for s in seqs if len(s) > idx]
        if not pool:
            break
        cand = [a for a, _ in Counter(s[idx] for s in pool).most_common() if ok(a, idx)]
        if not cand:  # берём то, что чаще всего качают в этот момент вообще
            cand = [a for a, _ in Counter(x for s in seqs for x in s[max(0, idx - 1):idx + 2]).most_common() if ok(a, idx)]
        if not cand:
            cand = [a for a in cap if ok(a, idx)]
            cand.sort(key=lambda a: -sum(s.count(a) for s in seqs))
        if not cand:
            break
        a = cand[0]
        out.append(a)
        have[a] += 1
        if tier_of(a):
            tiers.add(tier_of(a))
    exact = sum(1 for s in seqs if s[:min(10, len(out))] == out[:10])
    return out, exact


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--heroes", type=str, default="", help="только эти id героев через запятую (для отладки)")
    args = ap.parse_args()

    print("Константы…")
    heroes = get("constants/heroes")
    items = get("constants/items")
    abilities = get("constants/abilities")
    ability_ids = get("constants/ability_ids")
    hero_abilities = get("constants/hero_abilities")
    item_ids = get("constants/item_ids")
    only = {int(x) for x in args.heroes.split(",") if x}
    use_stratz = bool(os.environ.get("STRATZ_TOKEN"))
    print("STRATZ:", "включён" if use_stratz else "нет токена, только про-матчи")
    patches = get("constants/patch")
    patch_name = patches[-1]["name"] if patches else ""

    days = args.days
    patch_ts = 0
    if patches:
        from datetime import datetime
        patch_ts = datetime.fromisoformat(patches[-1]["date"].replace("Z", "+00:00")).timestamp()
        since_patch = int((time.time() - patch_ts) // 86400) + 1
        days = min(days, since_patch)
    patch_age = (time.time() - patch_ts) / 86400 if patch_ts else 999
    prev_patch_name = patches[-2]["name"] if len(patches) > 1 else ""
    # буквенные патчи (7.42a, 7.42b…) OpenDota отдельно не знает — берём их у Valve.
    # Билды считаем по всему большому патчу (нужен объём игр), а винрейты в «Мете» — с последнего буквенного
    meta_patch_ts, meta_patch_name = patch_ts, patch_name
    try:
        req = urllib.request.Request("https://www.dota2.com/datafeed/patchnoteslist?language=english",
                                     headers={"User-Agent": "dota-builds"})
        vp = json.load(urllib.request.urlopen(req, timeout=30)).get("patches") or []
        last = max((x for x in vp if str(x.get("patch_number", "")).startswith(patch_name)),
                   key=lambda x: x.get("patch_timestamp") or 0, default=None)
        if last and (last.get("patch_timestamp") or 0) > patch_ts + 86400:
            meta_patch_ts, meta_patch_name = last["patch_timestamp"], last["patch_number"]
            print(f"Буквенный патч {meta_patch_name}: винрейты в «Мете» считаются с него")
    except Exception as e:
        print(f"  ! список патчей Valve недоступен: {e}")
    # недельная статистика STRATZ первые дни после патча смешана со старым патчем
    fresh_patch = patch_age < 8
    print(f"Про-матчи за {days} дн., только патч {patch_name} (вышел {patch_age:.1f} дн. назад)…")
    rows = fetch_rows(days, patch_ts)
    for r in rows:
        if r.get("additional_units"):
            r["bear"] = bear_from_au(r.pop("additional_units"), item_ids)
    print(f"  медведь Lone Druid: инвентарь есть в {sum(1 for r in rows if r.get('bear') is not None)} про-играх")
    pro_match_count = len({r["match_id"] for r in rows})
    few_pro = pro_match_count < 60  # про-матчей на новом патче мало — строим статистику на Immortal-пабах

    # группировка по матчам для определения позиций
    matches = defaultdict(list)
    for r in rows:
        matches[r["match_id"]].append(r)
    for mid, ps in matches.items():
        for side in (True, False):
            team = [p for p in ps if (p["player_slot"] < 128) == side]
            for hid, n in assign_positions(team).items():
                for p in team:
                    if p["hero_id"] == hid:
                        p["pos"] = n

    def ab_name(aid):
        return ability_ids.get(str(aid))

    def is_build_item(key):
        it = items.get(key)
        if not it or key in CONSUMABLES or key.startswith("recipe_"):
            return False
        return bool(it.get("components")) or key in STANDALONE_OK or (it.get("cost") or 0) >= 1800

    comp_cache = {}

    def comp_of(key):
        """Все компоненты предмета (рекурсивно)."""
        if key not in comp_cache:
            res = set()
            for c in (items.get(key, {}).get("components") or []):
                res.add(c)
                res |= comp_of(c)
            comp_cache[key] = res
        return comp_cache[key]

    def first_buys_of(log):
        seen = {}
        for e in log:
            k = e["key"]
            if e["time"] > 0 and k not in seen and is_build_item(k):
                seen[k] = e["time"]
        for k, t in list(seen.items()):
            if any(t <= t2 and k in comp_of(k2) for k2, t2 in seen.items() if k2 != k):
                del seen[k]
        return seen

    # винрейты Immortal без перекоса: сводная статистика STRATZ по дням после патча
    winrates = None
    if use_stratz and patch_ts:
        first_full_day = (int(meta_patch_ts) // 86400 + 1) * 86400
        try:
            winrates = stratz.hero_winrates(first_full_day)
            if (not winrates or not winrates.get("days")) and meta_patch_ts != patch_ts:
                # по буквенному патчу ещё нет ни одного полного дня — пока считаем по всему большому патчу
                print("  по буквенному патчу ещё нет полного дня статистики — берём весь патч")
                meta_patch_ts, meta_patch_name = patch_ts, patch_name
                winrates = stratz.hero_winrates((int(patch_ts) // 86400 + 1) * 86400)
            if winrates:
                print(f"Винрейты Immortal (STRATZ): {winrates['days']} дн., "
                      f"{sum(g for g, _ in winrates['all'].values()) // 10} матчей")
        except Exception as e:  # noqa: BLE001
            print(f"  ! винрейты STRATZ не загрузились: {e}", file=sys.stderr)

    # Immortal-статистика заранее: по ней видно, на каких позициях героя играют
    imm_all, want = {}, set()
    empty_streak = 0
    if use_stratz:
        for hid_s, h in heroes.items():
            hid = int(hid_s)
            if only and hid not in only:
                continue
            tl = {t["name"]: t["level"] for t in hero_abilities.get(h["name"], {}).get("talents", [])}
            if empty_streak >= 8:  # недельная статистика STRATZ пуста (свежий патч) — не тратим лимит запросов
                imm_all[hid] = {}
                continue
            imm_all[hid] = stratz.fetch_hero(hid, item_ids, ability_ids, tl, is_build_item,
                                             {k: v.get("cost") for k, v in items.items()})
            empty_streak = 0 if imm_all[hid] else empty_streak + 1
            time.sleep(1.2)
        if empty_streak >= 8:
            print("  недельная статистика STRATZ пуста — запросы по героям пропущены")
        pro_cnt = Counter((r["hero_id"], r.get("pos")) for r in rows if r.get("pos"))
        wanted, popular = [], []
        # на каких позициях героя играют: из дневной статистики Immortal (надёжнее недельной — та бывает пустой)
        pos_games = {}
        if winrates:
            for pos in range(1, 6):
                for hid, (g_, _) in winrates.get(pos, {}).items():
                    pos_games.setdefault(hid, {})[pos] = g_
        if not pos_games:
            pos_games = {hid: {pos: v["games"] for pos, v in imm.items()} for hid, imm in imm_all.items()}
        for hid, by_pos in pos_games.items():
            if only and hid not in only:
                continue
            tot = sum(by_pos.values()) or 1
            for pos, g_ in by_pos.items():
                if g_ / tot >= 0.1:
                    (wanted if pro_cnt[(hid, pos)] < PUB_MIN else popular).append((hid, pos))
        print(f"  позиции для пабов: {len(wanted)} с малым числом про-игр, {len(popular)} остальных")
        want = set(wanted) | (set(popular) if few_pro else set())
        try:
            # сначала позиции, где про-игр мало, потом остальные популярные (для списка пабов)
            pub_rows = pubs.fetch(wanted + popular, item_ids, min_start=patch_ts)
        except Exception as e:  # noqa: BLE001
            print(f"  ! пабы не загрузились: {e}", file=sys.stderr)
            pub_rows = []
        # только матчи, где Immortal весь матч (а не один игрок среди Divine)
        before = len({r["match_id"] for r in pub_rows})
        pub_rows = [r for r in pub_rows if r["pos"] and (
            r["match_rank"] >= pubs.MIN_RANK if r.get("match_rank") is not None
            else (r.get("rank") is None or r["rank"] >= pubs.MIN_RANK))]
        print(f"  пабы: матчей Immortal целиком {len({r['match_id'] for r in pub_rows})} из {before}")
        for r in pub_rows:
            matches[r["match_id"]].append(r)
        rows.extend(pub_rows)

    # непредвзятые матчи топ-игроков лидерборда (пока только копим и пишем сводку в лог, на сайт не выводим)
    if patch_ts:  # без токена ladder.fetch отдаёт кеш
        try:
            lad = ladder.fetch(patch_ts)
            hn_ = {int(k): v["localized_name"] for k, v in heroes.items()}
            for line in ladder.summary(lad, hn_).splitlines():
                print("ЛАДДЕР:", line)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "solo.json").write_text(json.dumps(ladder.solo_stats(lad), separators=(",", ":")))
            # игры лидерборда идут и в паб-билды: в них все исходы подряд, поэтому по ним считаем винрейты
            have = {(r["match_id"], r["hero_id"]): r for r in rows if r.get("src") == "pub"}
            added = 0
            for r in ladder.to_rows(lad, item_ids, patch_ts):
                old_r = have.get((r["match_id"], r["hero_id"]))
                if old_r:
                    old_r["lad"] = True
                    continue
                rows.append(r)
                matches[r["match_id"]].append(r)
                added += 1
            print(f"  паб-билды: +{added} строк из игр лидерборда")
        except Exception as e:  # noqa: BLE001
            print(f"  ! лидерборд не загрузился: {e}", file=sys.stderr)

    fb_all = {}
    for r in rows:
        if r["purchase_log"]:
            fb_all[(r["match_id"], r["hero_id"])] = first_buys_of(pg_array(r["purchase_log"]))
    lifts = reasons.lift_table(matches, fb_all)
    item_names = {k: v.get("dname", k) for k, v in items.items()}
    components = {c for v in items.values() for c in (v.get("components") or [])}
    # все сапоги: сами boots и всё, что из них собирается (фазы, тредсы, арканы, гривзы, тревелы…)
    boots_set = {"boots"}
    for _ in range(4):
        boots_set |= {k for k, v in items.items() if set(v.get("components") or []) & boots_set}
    # «чистые» компоненты: входят в другие предметы, сами не собираются и не имеют активной способности
    raw_parts = {k for k in components if not (items.get(k, {}).get("components"))
                 and not any(ab.get("type") == "active" for ab in (items.get(k, {}).get("abilities") or []))
                 and k not in ("boots", "magic_stick", "wind_lace", "orb_of_venom", "blight_stone", "quelling_blade")}

    pub_groups = defaultdict(list)
    for r in rows:
        if r.get("src") == "pub" and r.get("pos") and r["purchase_log"] not in (None, "", "[]"):
            pub_groups[(r["hero_id"], r["pos"])].append(r)

    def fair(g):
        """Игра без перекоса по исходу: про-матч или игра из истории игрока лидерборда (не «гайд» STRATZ)."""
        return g.get("src", "pro") == "pro" or g.get("lad")

    def item_table(games_, fbs):
        """Частота и время предметов. Доля считается среди игр, которые дожили до времени покупки:
        дорогой предмет на 30-й минуте не «редкий», если половина игр закончилась на 25-й."""
        n_ = len(games_) or 1
        freq_ = Counter(k for fb in fbs for k in fb)
        times_ = defaultdict(list)
        for fb in fbs:
            for k, t in fb.items():
                times_[k].append(t)
        durs = [g.get("duration") or 10 ** 6 for g in games_]
        out_ = []
        for k, c in freq_.items():
            t_ = median(times_[k])
            reach = [i for i, d_ in enumerate(durs) if d_ >= (t_ or 0) + 180]
            if len(reach) >= max(5, 0.25 * n_):
                share = sum(1 for i in reach if k in fbs[i]) / len(reach)
            else:
                share = c / n_
            fg = [g for g, fb in zip(games_, fbs) if k in fb and fair(g)]
            won = sum(1 for g in fg if (g["player_slot"] < 128) == g["radiant_win"])
            out_.append({"key": k, "share": round(min(1, share), 2), "time": t_,
                         "wr": round(won / len(fg), 2) if len(fg) >= 15 else None, "n": c})
        return out_

    def add_alternatives(core_, item_stats_, fbs):
        """Слот «или»: предмет, который берут примерно в то же время, но почти никогда вместе с этим."""
        used = {c["key"] for c in core_}
        for c in core_:
            best_alt = None
            for x in item_stats_:
                if x["key"] in used or x["share"] < 0.1 or x["time"] is None or c["time"] is None:
                    continue
                if abs(x["time"] - c["time"]) > 420:
                    continue
                cc, xc = items.get(c["key"], {}).get("cost") or 0, items.get(x["key"], {}).get("cost") or 0
                if cc and xc and not (0.5 <= xc / cc <= 2):
                    continue  # альтернатива должна быть сопоставимой по цене
                both = sum(1 for fb in fbs if c["key"] in fb and x["key"] in fb)
                if both / max(1, min(c["n"], x["n"])) > 0.35:
                    continue
                if not best_alt or x["share"] > best_alt["share"]:
                    best_alt = x
            if best_alt:
                c["alt"] = {k: best_alt[k] for k in ("key", "share", "wr", "time", "n")}
                used.add(best_alt["key"])

    def game_cards(gs, fbs, standard_, med_gpm_, limit=12):
        cards = []
        for g, fb in sorted(zip(gs, fbs), key=lambda x: -x[0]["start_time"]):
            radiant = g["player_slot"] < 128
            adv = pg_array(g["gold_adv"]) or []
            team_adv = [a if radiant else -a for a in adv]
            early = team_adv[:STOMP_MINUTE + 1]
            stomp = (early and max(early) >= STOMP_ADV) or (
                med_gpm_ and g["gold_per_min"] and g["gold_per_min"] >= med_gpm_ * STOMP_GPM_RATIO)
            hard = bool(early) and min(early) <= HARD_ADV
            mates = matches.get(g["match_id"], [])
            enemies = [e["hero_id"] for e in mates if (e["player_slot"] < 128) != radiant]
            allies = [e["hero_id"] for e in mates if (e["player_slot"] < 128) == radiant and e["hero_id"] != g["hero_id"]]
            build = []
            for k, t in sorted(fb.items(), key=lambda kv: kv[1]):
                minute = max(0, t // 60)
                a = team_adv[minute] if minute < len(team_adv) else (team_adv[-1] if team_adv else None)
                odd = standard_ is not None and k not in standard_  # None — матч прошлого патча, сравнивать не с чем
                why = None
                if odd:
                    why = reasons.explain(k, t, team_adv, enemies,
                                          {e: fb_all.get((g["match_id"], e), {}) for e in enemies},
                                          heroes, lifts, item_names, components, g["duration"], raw_parts)
                build.append({"key": k, "time": t, "adv": a, "odd": odd, "why": why})
            used_items.update(fb)
            cards.append({
                "match": g["match_id"], "player": g["pro_name"] or "аноним",
                "src": g.get("src", "pro"), "rank": g.get("rank"),
                "league": g["league"], "date": g["start_time"], "dur": g["duration"],
                "win": radiant == g["radiant_win"], "k": g["kills"], "d": g["deaths"],
                "a": g["assists"], "gpm": g["gold_per_min"],
                "maxAdv": max(team_adv) if team_adv else None,
                "minAdv": min(team_adv) if team_adv else None,
                "flag": "stomp" if stomp else ("hard" if hard else None),
                "allies": allies, "enemies": enemies, "hero": g["hero_id"], "pos": g.get("pos"),
                "oldPatch": bool(patch_ts and g["start_time"] < patch_ts),
                "items": build,
            })
        if limit is None:
            return cards
        named = [c for c in cards if c["player"] != "аноним"]
        return (named + [c for c in cards if c["player"] == "аноним"])[:limit]

    def pub_cards(hid_, pos_, standard_):
        gs = pub_groups.get((hid_, pos_), [])
        fbs = [fb_all.get((g["match_id"], g["hero_id"]), {}) for g in gs]
        local = {i["key"] for i in item_table(gs, fbs) if i["share"] >= 0.12}
        gpm = median([g["gold_per_min"] for g in gs if g["gold_per_min"]])
        return game_cards(gs, fbs, standard_ | local, gpm)

    START_GOLD = 600
    BEAR_MIN = 10  # от стольких игр с известным инвентарём медведя показываем его билд
    BEAR_TRIVIAL = {"branches", "quelling_blade", "tango", "flask", "clarity", "tpscroll", "ward_observer",
                    "ward_sentry", "dust", "smoke_of_deceit", "enchanted_mango", "faerie_fire", "blood_grenade"}
    PUB_BUILD_MIN = 10   # меньше паб-игр — отдельный паб-билд не строим
    MIN_PRO_STD = 15     # от стольких про-игр «стандартный билд» для пометки необычных предметов берём из про

    def set_cost(cnt):
        return sum((items.get(k, {}).get("cost") or 0) * c for k, c in cnt.items())

    def opening(log):
        """Стартовый закуп (до горна) и докупка в первую минуту после горна.

        Если из купленного сразу собрали предмет (Stick + 2 Branches + рецепт = Magic Wand),
        в логе есть и компоненты, и сам предмет — компоненты убираем, иначе выходит «закуп на 1400».
        """
        evs = [dict(e) for e in log if e["time"] <= 60 and not e["key"].startswith("recipe_")]
        for i, e in enumerate(evs):
            comps = items.get(e["key"], {}).get("components") or []
            for c in comps:
                for prev in evs[:i]:
                    if prev["key"] == c and not prev.get("used"):
                        prev["used"] = True
                        break
        start = Counter(e["key"] for e in evs if e["time"] <= 0 and not e.get("used"))
        after = Counter(e["key"] for e in evs if 0 < e["time"] <= 60 and not e.get("used"))
        return start, after

    groups = defaultdict(list)
    for r in rows:
        if r.get("pos") and r["purchase_log"] and r["abilities"] not in (None, "", "{}"):
            if r.get("src") == "pub":
                continue  # пабы — отдельный билд (pub_groups)
            groups[(r["hero_id"], r["pos"])].append(r)

    standards, med_gpms, hero_item_share, hero_tl = {}, {}, {}, {}
    hero_index = []
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "heroes").mkdir(exist_ok=True)
    used_items, used_abilities = set(), set()

    for hid_s, h in sorted(heroes.items(), key=lambda kv: kv[1]["localized_name"]):
        hid = int(hid_s)
        if only and hid not in only:
            continue
        hname = h["name"]
        habil = hero_abilities.get(hname, {})
        talent_levels = {t["name"]: t["level"] for t in habil.get("talents", [])}
        hero_tl[hid] = talent_levels
        positions = {}

        def make_build(games, pos):
            n = len(games)
            fg_ = [g for g in games if fair(g)]
            wins = sum(1 for g in fg_ if (g["player_slot"] < 128) == g["radiant_win"])
            gpms = [g["gold_per_min"] for g in games if g["gold_per_min"]]
            med_gpm = median(gpms)

            # --- скиллы
            seqs, talent_picks = [], defaultdict(Counter)
            t_fair, t_won = defaultdict(Counter), defaultdict(Counter)
            for g in games:
                seq = []
                g_fair, g_won = fair(g), (g["player_slot"] < 128) == g["radiant_win"]
                for aid in pg_array(g["abilities"]):
                    nm = ab_name(aid)
                    if not nm or nm == "special_bonus_attributes":
                        continue
                    if nm.startswith("special_bonus"):
                        lvl = talent_levels.get(nm)
                        if lvl:
                            talent_picks[lvl][nm] += 1
                            if g_fair:
                                t_fair[lvl][nm] += 1
                                t_won[lvl][nm] += g_won
                        seq.append(nm)
                    elif nm in abilities:
                        if nm.endswith("_break") and nm[:-6] in abilities:
                            nm = nm[:-6]  # в части матчей очко в Tether пишется как Break Tether
                        seq.append(nm)
                seqs.append(seq)
            skill_seq, skill_exact = greedy_sequence(seqs, 19, talent_levels)
            used_abilities.update(s for s in skill_seq if not s.startswith("special_bonus"))
            talents = []
            for lvl in (1, 2, 3, 4):
                opts = [t for t, l in talent_levels.items() if l == lvl]
                total = sum(talent_picks[lvl].values()) or 1
                talents.append({
                    "level": [10, 15, 20, 25][lvl - 1],
                    "options": [{"name": t, "pick": round(talent_picks[lvl][t] / total, 2),
                                 "wr": round(t_won[lvl][t] / t_fair[lvl][t], 2) if t_fair[lvl][t] >= 15 else None}
                                for t in opts],
                    "sample": sum(talent_picks[lvl].values()),
                })

            # --- предметы
            start_counter = Counter()
            first_buy = []
            bear_buy = []
            start_sets = defaultdict(list)
            after_by_game = {}
            for g in games:
                log = pg_array(g["purchase_log"])
                start, after = opening(log)
                if start and set_cost(start) <= START_GOLD:
                    key_ = tuple(sorted(start.items()))
                    start_sets[key_].append(g)
                    after_by_game[id(g)] = tuple(sorted(after.items()))
                    for k, c in start.items():
                        start_counter[(k, c)] += 1
                seen = {}
                for e in log:
                    k = e["key"]
                    if e["time"] > 0 and k not in seen and is_build_item(k):
                        seen[k] = e["time"]
                # убираем компоненты, которые позже ушли в собранный предмет
                for k, t in list(seen.items()):
                    if any(t <= t2 and k in comp_of(k2) for k2, t2 in seen.items() if k2 != k):
                        del seen[k]
                bear = g.get("bear")
                if bear is not None:
                    # предметы из итогового инвентаря медведя — это билд медведя, а не героя
                    bset = set(bear) - BEAR_TRIVIAL
                    bear_buy.append((g, {k: t for k, t in seen.items() if k in bset}))
                    seen = {k: t for k, t in seen.items() if k not in bset}
                first_buy.append(seen)
            n_start = sum(len(v) for v in start_sets.values()) or 1
            start_items = []
            best = {}
            for (k, c), cnt in start_counter.items():
                if cnt / n_start >= 0.3 and (k not in best or cnt > best[k][1]):
                    best[k] = (c, cnt)
            for k, (c, cnt) in sorted(best.items(), key=lambda kv: -kv[1][1]):
                start_items.append({"key": k, "count": c, "share": round(cnt / n_start, 2)})
            # готовые варианты стартового закупа (целые наборы, как их брали в играх)
            start_variants = []
            for combo, gs in sorted(start_sets.items(), key=lambda kv: -len(kv[1]))[:2]:
                if len(gs) < 2 and start_variants:
                    break
                fgs = [g for g in gs if fair(g)]
                won = sum(1 for g in fgs if (g["player_slot"] < 128) == g["radiant_win"])
                by_cost = lambda i: -(items.get(i["key"], {}).get("cost") or 0) * i["count"]
                its = sorted(({"key": k, "count": c} for k, c in combo), key=by_cost)
                # что докупают в первую минуту после горна (самый частый вариант у этого набора)
                afters = Counter(after_by_game.get(id(g), ()) for g in gs)
                after_combo, after_n = afters.most_common(1)[0]
                after_items = sorted(({"key": k, "count": c} for k, c in after_combo), key=by_cost)
                players = [p for p, _ in Counter(g["pro_name"] for g in gs if g["pro_name"]).most_common(3)]
                start_variants.append({
                    "items": its, "games": len(gs), "share": round(len(gs) / n, 2),
                    "wr": round(won / len(fgs), 2) if len(fgs) >= 10 else None,
                    "cost": set_cost(dict(combo)),
                    "after": after_items, "afterGames": after_n if after_items else 0,
                    "players": players,
                })
                used_items.update(i["key"] for i in its + after_items)
            # у Lone Druid предметы героя считаем только по играм, где известен инвентарь медведя —
            # иначе в билд героя попадут вещи медведя
            if len(bear_buy) >= BEAR_MIN:
                bear_ids = {id(g) for g, _ in bear_buy}
                pairs = [(g, fb) for g, fb in zip(games, first_buy) if id(g) in bear_ids]
                item_stats = item_table([g for g, _ in pairs], [fb for _, fb in pairs])
                b_stats = item_table([g for g, _ in bear_buy], [fb for _, fb in bear_buy])
                bear_b = {
                    "games": len(bear_buy),
                    "core": sorted([i for i in b_stats if i["share"] >= 0.35], key=lambda i: i["time"])[:6],
                    "situational": sorted([i for i in b_stats if 0.12 <= i["share"] < 0.35],
                                          key=lambda i: -i["share"])[:8],
                }
                used_items.update(i["key"] for i in bear_b["core"] + bear_b["situational"])
            else:
                item_stats = item_table(games, first_buy)
                bear_b = None
            core = sorted([i for i in item_stats if i["share"] >= 0.4], key=lambda i: i["time"])
            # в основном билде только одни сапоги: самые популярные собранные (коричневые — лишь если других нет),
            # остальные сапоги уходят в ситуативные
            cb = [i for i in core if i["key"] in boots_set]
            moved = []
            if len(cb) > 1:
                upgraded = [i for i in cb if i["key"] != "boots"] or cb
                keep = max(upgraded, key=lambda i: i["share"])
                moved = [i for i in cb if i is not keep and i["key"] != "boots"]
                core = [i for i in core if i["key"] not in boots_set or i is keep]
            core = core[:7]
            situational = sorted([i for i in item_stats if 0.12 <= i["share"] < 0.4] + moved,
                                 key=lambda i: -i["share"])[:10]
            add_alternatives(core, item_stats, first_buy)
            if any(i["key"] in boots_set for i in core):
                for c in core:  # «или» не должно подсовывать вторые сапоги к не-сапогам
                    if c["key"] not in boots_set and c.get("alt") and c["alt"]["key"] in boots_set:
                        del c["alt"]
            alt_keys = {c["alt"]["key"] for c in core if c.get("alt")}
            situational = [i for i in situational if i["key"] not in alt_keys]  # уже стоит в билде через «или»
            standard = {i["key"] for i in core + situational} | {c["alt"]["key"] for c in core if c.get("alt")}
            used_items.update(i["key"] for i in start_items + core + situational)
            used_items.update(c["alt"]["key"] for c in core if c.get("alt"))
            build = {
                "games": n, "wr": round(wins / len(fg_), 2) if len(fg_) >= 10 else None, "gpm": med_gpm,
                "fairGames": len(fg_),
                "skills": skill_seq, "skillsExact": skill_exact,
                "talents": talents, "start": start_items, "startSets": start_variants, "core": core,
                "situational": situational,
                **({"bear": bear_b} if bear_b else {}),
            }
            if bear_b:
                standard |= {i["key"] for i in bear_b["core"] + bear_b["situational"]}
            return build, standard, med_gpm, item_stats, first_buy

        for pos in (1, 2, 3, 4, 5):
            pro_g = groups.get((hid, pos), [])
            pub_g = [g for g in pub_groups.get((hid, pos), []) if g["abilities"] not in (None, "", "{}")]
            if not pro_g and len(pub_g) < PUB_BUILD_MIN:
                continue
            pro_b = pub_b = None
            if pro_g:
                pro_b, standard, med_gpm, item_stats, first_buy = make_build(pro_g, pos)
                pro_games = game_cards(pro_g, first_buy, standard, med_gpm)
            if len(pub_g) >= PUB_BUILD_MIN:
                pub_b, p_std, p_gpm, p_stats, _ = make_build(pub_g, pos)
            if pro_b and (pro_b["games"] >= MIN_PRO_STD or not pub_b):
                base_std, base_gpm, base_stats = standard, med_gpm, item_stats
            else:
                base_std, base_gpm, base_stats = p_std, p_gpm, p_stats
            hero_item_share[(hid, pos)] = {i["key"]: i["share"] for i in base_stats}
            standards[(hid, pos)] = base_std
            med_gpms[(hid, pos)] = base_gpm
            if not pro_b:
                pro_games = []
                pro_b = {"games": 0, "wr": None, "gpm": None, "fairGames": 0, "skills": [], "skillsExact": 0,
                         "talents": [{"level": [10, 15, 20, 25][l - 1], "sample": 0,
                                      "options": [{"name": t, "pick": 0} for t, tl in talent_levels.items() if tl == l]}
                                     for l in (1, 2, 3, 4)],
                         "start": [], "startSets": [], "core": [], "situational": []}
            positions[pos] = {
                **pro_b,
                "pub": pub_b,
                "pubGames": len(pub_g),
                "immWr": (lambda gw: round(gw[1] / gw[0], 3) if gw and gw[0] else None)(
                    (winrates or {}).get(pos, {}).get(hid)),
                "immGames": ((winrates or {}).get(pos, {}).get(hid) or [0])[0],
                "pro": pro_games, "pubs": pub_cards(hid, pos, base_std),
            }
        if use_stratz:
            imm = imm_all.get(hid, {})
            for pos, st in imm.items():
                used_items.update(i["key"] for i in st["core"] + st["situational"] + st["start"])
                used_abilities.update(x["name"] for x in st["maxOrder"])
                if pos not in positions:
                    positions[pos] = {"games": 0, "wr": None, "gpm": None, "skills": [], "skillsExact": 0,
                                      "talents": [{"level": [10, 15, 20, 25][l - 1], "sample": 0,
                                                   "options": [{"name": t, "pick": 0} for t, tl in talent_levels.items() if tl == l]}
                                                  for l in (1, 2, 3, 4)],
                                      "start": [], "core": [], "situational": [], "pro": [],
                                      "pubs": pub_cards(hid, pos, set())}
                if not fresh_patch:
                    positions[pos]["imm"] = st
            if imm:
                print(f"  {h['localized_name']}: Immortal {', '.join(f'pos{p}={imm[p]["games"]}' for p in sorted(imm))}")
        if positions:
            (OUT / "heroes" / f"{hid}.json").write_text(
                json.dumps({"id": hid, "positions": positions}, ensure_ascii=False, separators=(",", ":")))
        hero_index.append({
            "id": hid, "name": h["localized_name"], "short": hname.replace("npc_dota_hero_", ""),
            "img": CDN + h["img"].split("?")[0], "attr": h.get("primary_attr"),
            "roles": h.get("roles", []),
            "positions": {p: positions[p]["games"] for p in positions},
            "imm": {p: positions[p]["imm"]["games"] for p in positions if "imm" in positions[p]},
            "pubs": {p: positions[p].get("pubGames", 0) for p in positions},
        })

    def skill_seq_of(g, tl):
        seq = []
        for aid in pg_array(g["abilities"]):
            nm = ab_name(aid)
            if not nm or nm == "special_bonus_attributes":
                continue
            if nm.startswith("special_bonus") or nm in abilities:
                if nm.endswith("_break") and nm[:-6] in abilities:
                    nm = nm[:-6]
                seq.append(nm)
        return seq

    def player_hero_build(hid_, pgs, pfs):
        """Как конкретный игрок играет конкретного героя: прокачка, закуп, его особенности."""
        n_ = len(pgs)
        if not n_:
            return None
        tl = hero_tl.get(hid_, {})
        seqs = [skill_seq_of(g, tl) for g in pgs]
        seq, _ = greedy_sequence(seqs, 19, tl)
        used_abilities.update(x for x in seq if not x.startswith("special_bonus"))
        picks = defaultdict(Counter)
        for sq in seqs:
            for x in sq:
                if tl.get(x):
                    picks[tl[x]][x] += 1
        talents_ = []
        for lvl in (1, 2, 3, 4):
            opts = [t for t, l in tl.items() if l == lvl]
            tot = sum(picks[lvl].values()) or 1
            talents_.append({"level": [10, 15, 20, 25][lvl - 1], "sample": sum(picks[lvl].values()),
                             "options": [{"name": t, "pick": round(picks[lvl][t] / tot, 2)} for t in opts]})
        pos_ = Counter(g.get("pos") for g in pgs if g.get("pos")).most_common(1)
        pos_ = pos_[0][0] if pos_ else None
        table = item_table(pgs, pfs)
        core_ = sorted([i for i in table if i["share"] >= 0.4], key=lambda i: i["time"] or 0)
        sit_ = sorted([i for i in table if 0.2 <= i["share"] < 0.4], key=lambda i: -i["share"])[:8]
        general = hero_item_share.get((hid_, pos_), {})
        signature = []
        for i in table:
            gsh = general.get(i["key"], 0)
            if i["n"] >= 2 and i["share"] >= 0.3 and gsh < 0.15:
                signature.append({**i, "general": gsh})
        signature.sort(key=lambda i: -i["share"])
        # стартовый закуп игрока на этом герое
        sets_ = defaultdict(list)
        for g in pgs:
            st, af = opening(pg_array(g["purchase_log"]))
            if st and set_cost(st) <= START_GOLD:
                sets_[tuple(sorted(st.items()))].append(tuple(sorted(af.items())))
        start_ = None
        if sets_:
            combo, afs = max(sets_.items(), key=lambda kv: len(kv[1]))
            af_combo, af_n = Counter(afs).most_common(1)[0]
            start_ = {"items": [{"key": k, "count": c} for k, c in combo], "games": len(afs),
                      "cost": set_cost(dict(combo)),
                      "after": [{"key": k, "count": c} for k, c in af_combo], "afterGames": af_n if af_combo else 0}
            used_items.update(k for k, _ in combo)
            used_items.update(k for k, _ in af_combo)
        used_items.update(i["key"] for i in core_ + sit_ + signature)
        wins_ = sum(1 for g in pgs if (g["player_slot"] < 128) == g["radiant_win"])
        return {"games": n_, "wins": wins_, "pos": pos_, "skills": seq, "talents": talents_,
                "core": core_, "situational": sit_, "signature": signature[:5], "start": start_,
                "heroWr": None}

    # --- про-игроки: карточки и история матчей
    # История игрока — за PLAYER_DAYS дней независимо от патча (билды героев — только текущий патч)
    PLAYER_DAYS = 30
    hist = [r for r in fetch_rows(PLAYER_DAYS) if r["start_time"] < patch_ts] if patch_ts else []
    hist_matches = defaultdict(list)
    for r in hist:
        hist_matches[r["match_id"]].append(r)
    for mid, ps in hist_matches.items():
        for side in (True, False):
            team = [p for p in ps if (p["player_slot"] < 128) == side]
            for hid_, n_ in assign_positions(team).items():
                for p_ in team:
                    if p_["hero_id"] == hid_:
                        p_["pos"] = n_
        matches[mid] = ps
        for r in ps:
            if r["purchase_log"]:
                fb_all[(mid, r["hero_id"])] = first_buys_of(pg_array(r["purchase_log"]))
    print(f"История про-игроков: +{len(hist_matches)} матчей прошлого патча")
    by_player = defaultdict(list)
    for r in rows + hist:
        if r.get("src", "pro") == "pro" and r.get("account_id") and r.get("pro_name") and r["purchase_log"]:
            by_player[r["account_id"]].append(r)
    import shutil
    shutil.rmtree(OUT / "players", ignore_errors=True)  # игроки, которых больше нет в выборке, не должны оставаться
    (OUT / "players").mkdir(exist_ok=True)
    player_index = []
    for acc, gs in by_player.items():
        if only and not any(g["hero_id"] in only for g in gs):
            continue
        fbs = [fb_all.get((g["match_id"], g["hero_id"]), {}) for g in gs]
        cards = []
        for g, fb in zip(gs, fbs):
            key = (g["hero_id"], g.get("pos"))
            old = patch_ts and g["start_time"] < patch_ts
            cards += game_cards([g], [fb], None if old else standards.get(key, set()), med_gpms.get(key), limit=None)
        cards.sort(key=lambda c: -c["date"])
        heroes_stat = defaultdict(lambda: [0, 0])
        pos_cnt = Counter()
        for c in cards:
            heroes_stat[c["hero"]][0] += 1
            heroes_stat[c["hero"]][1] += c["win"]
            if c["pos"]:
                pos_cnt[c["pos"]] += 1
        wins = sum(c["win"] for c in cards)
        hs = sorted(({"id": h, "games": v[0], "wins": v[1]} for h, v in heroes_stat.items()),
                    key=lambda x: (-x["games"], -x["wins"]))
        main_pos = pos_cnt.most_common(1)[0][0] if pos_cnt else None
        hero_builds = {}
        by_hero = defaultdict(list)
        for g, fb in zip(gs, fbs):
            by_hero[g["hero_id"]].append((g, fb))
        for hid_, lst in by_hero.items():
            # билд игрока на герое — по текущему патчу; если там игр нет, по прошлому (с пометкой)
            cur = [(g, fb) for g, fb in lst if not (patch_ts and g["start_time"] < patch_ts)]
            use = cur or lst
            hb = player_hero_build(hid_, [g for g, _ in use], [fb for _, fb in use])
            if hb:
                hb["oldPatch"] = not cur
                hb["prevPatch"] = prev_patch_name
            if hb:
                hero_builds[hid_] = hb
        cur_games = sum(1 for c in cards if not c.get("oldPatch"))
        info = {"id": acc, "name": gs[0]["pro_name"], "curGames": cur_games, "team": next((g.get("team") for g in gs if g.get("team")), None),
                "games": len(cards), "wins": wins, "pos": main_pos, "posCount": dict(pos_cnt), "heroes": hs,
                "last": cards[0]["date"] if cards else 0}
        (OUT / "players" / f"{acc}.json").write_text(
            json.dumps({**info, "matches": cards, "builds": hero_builds}, ensure_ascii=False, separators=(",", ":")))
        player_index.append(info)
    player_index.sort(key=lambda p: (-p["games"], p["name"].lower()))
    (OUT / "players.json").write_text(json.dumps(player_index, ensure_ascii=False, separators=(",", ":")))
    print(f"Про-игроков: {len(player_index)}")

    # --- мета: винрейт и популярность героев на текущем патче (про + Immortal-пабы)
    meta_stat = defaultdict(lambda: {"games": 0, "wins": 0, "pos": defaultdict(lambda: [0, 0])})
    all_matches = {r["match_id"] for r in rows}
    for r in rows:
        if not r.get("hero_id"):
            continue
        m_ = meta_stat[r["hero_id"]]
        won = (r["player_slot"] < 128) == r["radiant_win"]
        m_["games"] += 1
        m_["wins"] += won
        if r.get("pos"):
            m_["pos"][r["pos"]][0] += 1
            m_["pos"][r["pos"]][1] += won
    if winrates and winrates.get("all"):
        # мета по всем Immortal-играм STRATZ (без перекоса «гайдовых» пабов)
        total_games = sum(g for g, _ in winrates["all"].values())
        meta_matches = total_games // 10
        meta_list = []
        for h, (g_, w_) in winrates["all"].items():
            if not g_:
                continue
            tr = winrates.get("trend", {})
            meta_list.append({"id": h, "games": g_, "wins": w_, "wr": round(w_ / g_, 3),
                              "pick": round(g_ / max(1, meta_matches), 3),
                              "trend": tr.get("all", {}).get(h),
                              "posTrend": {p_: tr[p_][h] for p_ in range(1, 6) if tr.get(p_, {}).get(h)},
                              "pos": {p_: {"games": winrates[p_].get(h, [0, 0])[0], "wins": winrates[p_].get(h, [0, 0])[1]}
                                      for p_ in range(1, 6) if winrates[p_].get(h)}})
        meta_source = "все игры в ранге Immortal (STRATZ)"
    else:
        meta_matches = len(all_matches)
        meta_source = "про-матчи и Immortal-пабы"
    meta_list = meta_list if winrates and winrates.get("all") else [{"id": h, "games": v["games"], "wins": v["wins"], "wr": round(v["wins"] / v["games"], 3),
                  "pick": round(v["games"] / max(1, len(all_matches)), 3),
                  "pos": {p_: {"games": g_, "wins": w_} for p_, (g_, w_) in v["pos"].items()}}
                 for h, v in meta_stat.items()]
    # статистика по дням для выбора периода на сайте: «последние 8 дней» и «весь текущий патч»
    daily = None
    if use_stratz and patch_ts:
        try:
            first_full_day = (int(meta_patch_ts) // 86400 + 1) * 86400
            since = min(first_full_day, (int(time.time()) // 86400 - 9) * 86400)
            daily = stratz.hero_daily(since)
            if daily:
                print(f"По дням: {len(daily['days'])} дн. для выбора периода")
        except Exception as e:  # noqa: BLE001
            print(f"  ! статистика по дням не загрузилась: {e}", file=sys.stderr)
    if daily:
        for x in meta_list:
            x["d"] = daily["data"].get(x["id"], {})
    (OUT / "meta.json").write_text(json.dumps({"matches": meta_matches, "source": meta_source, "updated": int(time.time()),
                                               "days": (winrates or {}).get("days", 0),
                                               "dayList": (daily or {}).get("days", []),
                                               "patchDay": (int(meta_patch_ts) // 86400 + 1) * 86400 if meta_patch_ts else 0,
                                               "patch": meta_patch_name,
                                               "pro": pro_match_count, "heroes": meta_list},
                                              ensure_ascii=False, separators=(",", ":")))
    hn = {int(k): v["localized_name"] for k, v in heroes.items()}
    solid = sorted([x for x in meta_list if x["games"] >= 20], key=lambda x: -x["wr"])
    print(f"МЕТА: {meta_matches} матчей ({meta_source})")
    print("МЕТА винрейт:", "; ".join(f"{hn.get(x['id'])} {x['wr']:.0%} ({x['games']})" for x in solid[:15]))
    print("МЕТА популярность:", "; ".join(f"{hn.get(x['id'])} {x['pick']:.0%} ({x['wr']:.0%})"
                                         for x in sorted(meta_list, key=lambda x: -x["games"])[:15]))

    # словари для отображения
    item_dict = {k: {"name": items[k].get("dname", k), "img": CDN + items[k]["img"].split("?")[0],
                     "cost": items[k].get("cost")}
                 for k in used_items if k in items and items[k].get("img")}
    # тексты талантов с реальными числами (из STRATZ), иначе OpenDota с плейсхолдерами
    resolved = {}
    tfile = Path(__file__).with_name("talents_en.json")
    if tfile.exists():
        resolved = json.loads(tfile.read_text())
    # самые свежие тексты — из официальных данных Valve (числа текущего патча)
    try:
        resolved.update(valve.talent_texts(sorted(int(h) for h in heroes)))
        print(f"Таланты из данных Valve: {len(resolved)}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! таланты Valve не загрузились: {e}", file=sys.stderr)
    talent_names = {}
    for hname, ha in hero_abilities.items():
        for t in ha.get("talents", []):
            talent_names[t["name"]] = resolved.get(t["name"]) or abilities.get(t["name"], {}).get("dname", t["name"])
    # таланты, которых ещё нет в справочнике OpenDota (новые в патче), тоже подписываем
    for k, v in resolved.items():
        talent_names.setdefault(k, v)
    ab_dict = {k: {"name": abilities[k].get("dname", k),
                   "img": CDN + abilities[k]["img"] if abilities[k].get("img") else None}
               for k in used_abilities if k in abilities}

    meta = {
        "updated": int(time.time()), "days": days, "patch": patch_name,
        "matches": len(matches), "stratz": use_stratz and not fresh_patch,
        "patchDate": int(patch_ts), "freshPatch": fresh_patch, "prevPatch": prev_patch_name, "proMatches": pro_match_count,
        "pubMatches": len({r["match_id"] for r in rows if r.get("src") == "pub"}),
        "thresholds": {"stompAdv": STOMP_ADV, "stompMinute": STOMP_MINUTE,
                       "stompGpm": STOMP_GPM_RATIO, "hardAdv": HARD_ADV},
    }
    (OUT / "index.json").write_text(json.dumps(
        {"meta": meta, "heroes": hero_index, "items": item_dict, "abilities": ab_dict,
         "talents": talent_names}, ensure_ascii=False, separators=(",", ":")))
    print(f"Готово: {len(matches)} матчей, {sum(1 for h in hero_index if h['positions'])} героев с данными")


if __name__ == "__main__":
    main()
