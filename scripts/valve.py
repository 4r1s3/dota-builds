"""Официальные данные Valve (dota2.com/datafeed): тексты талантов с актуальными числами текущего патча."""
import json
import re
import sys
import time
import urllib.request

FEED = "https://www.dota2.com/datafeed/herodata?language={lang}&hero_id={hid}"


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dota-builds/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print(f"  ! Valve datafeed: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))
    return None


def _fmt(v):
    if isinstance(v, list):
        v = v[0] if v else None
    if v is None:
        return None
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:g}"


def resolve_talents(hero):
    """{'special_bonus_...': '+1.5s Overcharge Duration'} для одного героя из ответа datafeed."""
    # значения талантов лежат в special_values способностей, в поле bonuses: [{name: талант, value}]
    bonus = {}
    for a in hero.get("abilities", []) + hero.get("facet_abilities", []):
        for sv in a.get("special_values", []):
            for b in sv.get("bonuses") or []:
                bonus.setdefault(b["name"], []).append((sv["name"], b.get("value")))
    out = {}
    for t in hero.get("talents", []):
        name, text = t.get("name"), t.get("name_loc") or ""
        if not name or not text:
            continue
        own = {sv["name"]: sv.get("values_float") for sv in t.get("special_values", [])}
        mine = bonus.get(name, [])

        def value(ph):
            if ph in own:
                return _fmt(own[ph])
            for svn, val in mine:
                if ph in (svn, "bonus_" + svn) or ph.replace("bonus_", "", 1) == svn:
                    return _fmt(val)
            if len(mine) == 1:  # у таланта одно значение — оно и есть
                return _fmt(mine[0][1])
            if len(own) == 1:
                return _fmt(next(iter(own.values())))
            return None

        ok = True

        def sub(m):
            nonlocal ok
            v = value(m.group(1))
            if v is None:
                ok = False
                return "?"
            return v
        resolved = re.sub(r"\{s:([^}]+)\}", sub, text).replace("%%", "%")
        resolved = re.sub(r"<[^>]+>", "", resolved).strip()
        if ok:
            out[name] = resolved
    return out


def talent_texts(hero_ids, lang="english"):
    out = {}
    for hid in hero_ids:
        d = _get(FEED.format(lang=lang, hid=hid))
        try:
            hero = d["result"]["data"]["heroes"][0]
        except (TypeError, KeyError, IndexError):
            continue
        out.update(resolve_talents(hero))
        time.sleep(0.2)
    return out
