"""Почему купили нестандартный предмет: правила по смыслу предмета + статистика про-матчей.

Теги героев — ручной список; при изменениях в патчах его стоит поправлять.
"""
from collections import Counter, defaultdict

TAGS = {
    "invis": ("невидимость", {
        "riki", "clinkz", "bounty_hunter", "weaver", "nyx_assassin", "invoker", "mirana",
        "templar_assassin", "hoodwink", "sand_king", "void_spirit", "kez"}),
    "heal": ("лечение и реген", {
        "necrolyte", "alchemist", "huskar", "morphling", "abaddon", "oracle", "dazzle", "omniknight",
        "warlock", "chen", "enchantress", "treant", "witch_doctor", "undying", "life_stealer",
        "skeleton_king", "wisp", "dragon_knight", "bristleback", "winter_wyvern", "lich", "dawnbreaker",
        "pudge", "timbersaw", "shredder", "visage", "sven"}),
    "evasion": ("уклонение", {"phantom_assassin", "windrunner", "brewmaster", "troll_warlord", "monkey_king"}),
    "break": ("пассивки, которые выключает Break", {
        "bristleback", "phantom_assassin", "spectre", "huskar", "viper", "faceless_void", "slark",
        "troll_warlord", "medusa", "sniper", "tiny", "mars", "ursa", "skeleton_king", "chaos_knight",
        "drow_ranger", "juggernaut", "life_stealer", "morphling", "luna", "antimage",
        "leshrac", "terrorblade", "wisp"}),
    "illusions": ("иллюзии и саммоны", {
        "phantom_lancer", "naga_siren", "terrorblade", "chaos_knight", "meepo", "arc_warden", "monkey_king",
        "broodmother", "lycan", "furion", "enigma", "beastmaster", "visage", "lone_druid", "warlock",
        "shadow_demon", "venomancer", "invoker"}),
    "magic": ("магический урон", {
        "lina", "lion", "zuus", "skywrath_mage", "leshrac", "tinker", "storm_spirit", "queenofpain",
        "invoker", "puck", "techies", "necrolyte", "death_prophet", "pugna", "nyx_assassin", "ogre_magi",
        "obsidian_destroyer", "ember_spirit", "shadow_shaman", "jakiro", "crystal_maiden", "lich",
        "ancient_apparition", "witch_doctor", "earthshaker", "dark_willow", "grimstroke", "snapfire",
        "venomancer", "viper", "razor", "phoenix", "sand_king", "silencer", "keeper_of_the_light"}),
    "targeted": ("контроль в цель", {
        "doom_bringer", "lion", "shadow_shaman", "bane", "legion_commander", "batrider", "beastmaster",
        "rubick", "nyx_assassin", "pudge", "grimstroke", "winter_wyvern", "shadow_demon", "oracle",
        "vengefulspirit", "dragon_knight", "skeleton_king", "chaos_knight", "ogre_magi", "silencer",
        "night_stalker", "spirit_breaker", "sven", "lina", "zuus", "pugna", "huskar", "slardar"}),
    "rightclick": ("урон с руки", {
        "phantom_assassin", "juggernaut", "sven", "troll_warlord", "ursa", "drow_ranger", "sniper",
        "luna", "medusa", "terrorblade", "faceless_void", "slark", "antimage", "spectre", "life_stealer",
        "gyrocopter", "monkey_king", "lycan", "chaos_knight", "phantom_lancer", "naga_siren", "kez",
        "muerta", "clinkz", "weaver", "templar_assassin", "skeleton_king", "morphling", "razor",
        "shadow_fiend", "nevermore", "bloodseeker", "riki", "bounty_hunter", "marci", "dragon_knight"}),
    "escape": ("мобильность и побег", {
        "antimage", "queenofpain", "storm_spirit", "ember_spirit", "puck", "void_spirit", "faceless_void",
        "slark", "weaver", "morphling", "mirana", "pangolier", "earth_spirit", "phoenix", "batrider",
        "windrunner", "riki", "clinkz", "templar_assassin", "kez", "hoodwink", "marci", "monkey_king"}),
}

# предметы-сигналы во вражеских покупках
ENEMY_ITEMS = {
    "invis": ({"invis_sword", "silver_edge", "glimmer_cape", "shadow_amulet"}, "невидимость"),
    "evasion": ({"butterfly", "talisman_of_evasion", "heavens_halberd"}, "уклонение"),
    "dispellable": ({"ghost", "glimmer_cape", "aeon_disk", "eternal_shroud", "force_staff", "hurricane_pike",
                     "ethereal_blade", "lotus_orb", "pipe", "hood_of_defiance", "mekansm", "guardian_greaves",
                     "solar_crest", "sphere", "black_king_bar"}, "защитные предметы"),
    "lifesteal": ({"satanic", "heart", "mekansm", "guardian_greaves", "holy_locket", "vladmir",
                   "bloodstone", "octarine_core", "kaya_and_sange", "sange_and_yasha", "sange"}, "реген и лечение"),
}

# предмет -> (теги героев, ключи вражеских предметов, текст «зачем»)
RULES = {
    "spirit_vessel": (["heal"], ["lifesteal"], "режет лечение"),
    "urn_of_shadows": (["heal"], [], "лечение/добивание"),
    "shivas_guard": (["heal", "rightclick", "illusions"], ["lifesteal"], "режет лечение и скорость атаки"),
    "skadi": (["heal"], ["lifesteal"], "режет лечение"),
    "eye_of_skadi": (["heal"], ["lifesteal"], "режет лечение"),
    "gem": (["invis"], ["invis"], "видеть невидимок"),
    "dust": (["invis"], ["invis"], "видеть невидимок"),
    "monkey_king_bar": (["evasion"], ["evasion"], "пробивает уклонение"),
    "bloodthorn": (["evasion", "escape", "magic"], ["evasion"], "пробивает уклонение и молчанка"),
    "silver_edge": (["break"], [], "Break выключает пассивки и врождённые способности"),
    "nullifier": ([], ["dispellable"], "снимает защитные эффекты"),
    "diffusal_blade": (["escape"], ["dispellable"], "развеивает и замедляет"),
    "black_king_bar": (["magic", "targeted"], [], "защита от магии и контроля"),
    "pipe": (["magic"], [], "щит от магического урона"),
    "glimmer_cape": (["magic"], [], "защита от магии"),
    "eternal_shroud": (["magic"], [], "защита от магии"),
    "mage_slayer": (["magic"], [], "против магов"),
    "hood_of_defiance": (["magic"], [], "защита от магии"),
    "sphere": (["targeted"], [], "блокирует спелл в цель"),
    "lotus_orb": (["targeted"], [], "отражает спелл в цель"),
    "aeon_disk": (["magic", "rightclick", "targeted"], [], "переживает бёрст"),
    "heavens_halberd": (["rightclick"], [], "разоружает керри"),
    "ghost": (["rightclick"], [], "защита от урона с руки"),
    "crimson_guard": (["rightclick", "illusions"], [], "блок физ. урона"),
    "assault": (["rightclick", "illusions"], [], "броня против физ. урона"),
    "blade_mail": (["rightclick"], [], "отражает урон"),
    "solar_crest": (["rightclick"], [], "броня и уклонение"),
    "butterfly": (["rightclick"], [], "уклонение от атак"),
    "orchid": (["escape"], [], "молчанка на мобильного героя"),
    "abyssal_blade": (["escape"], ["dispellable"], "контроль сквозь BKB"),
    "sheepstick": (["escape"], [], "надёжный контроль"),
    "rod_of_atos": (["escape"], [], "держит мобильного героя"),
    "gungir": (["escape", "illusions"], [], "держит и чистит иллюзии"),
    "cyclone": (["targeted"], [], "развеивает и уводит из контроля"),
    "wind_waker": (["targeted"], [], "уводит из контроля"),
    "mjollnir": (["illusions"], [], "чистит иллюзии и саммонов"),
    "maelstrom": (["illusions"], [], "чистит иллюзии и саммонов"),
    "bfury": (["illusions"], [], "сплеш по иллюзиям"),
    "radiance": (["illusions"], [], "урон по иллюзиям"),
    "force_staff": (["targeted", "escape"], [], "спасает союзника"),
    "hurricane_pike": (["escape", "rightclick"], [], "дистанция от ближников"),
    "manta": (["targeted"], [], "развеивает контроль"),
    "satanic": (["rightclick"], [], "лечение в драке"),
    "heart": (["magic", "rightclick"], [], "живучесть"),
    "pavise": (["rightclick"], [], "щит от физ. урона"),
    "ward_sentry": (["invis"], ["invis"], "видеть невидимок"),
}
# предметы, которые берут не «против кого-то», а ради самой механики
GENERAL = {
    "blink": "мобильность: добраться до врага, инициировать и сломать его позиционку",
    "overwhelming_blink": "мобильность и инициация с уроном по области",
    "swift_blink": "мобильность и инициация, бонус к ловкости",
    "arcane_blink": "мобильность и быстрые касты после прыжка",
    "travel_boots": "мобильность по карте: сплит-пуш и телепорты к драке",
    "travel_boots_2": "мобильность по карте: сплит-пуш и телепорты к героям",
}
GREEDY = {"rapier", "greater_crit", "moon_shard", "ultimate_scepter_2", "hand_of_midas", "bfury",
          "radiance", "travel_boots", "travel_boots_2", "butterfly", "daedalus", "divine_rapier"}


def lift_table(rows_by_match, first_buys):
    """Для каждого предмета: во сколько раз чаще его берут при конкретном враге.

    first_buys: {(match_id, hero_id): {item: time}}
    """
    item_n = Counter()
    pair = defaultdict(Counter)
    enemy_n = Counter()
    total = 0
    for mid, ps in rows_by_match.items():
        for p in ps:
            fb = first_buys.get((mid, p["hero_id"]))
            if fb is None:
                continue
            total += 1
            enemies = [e["hero_id"] for e in ps if (e["player_slot"] < 128) != (p["player_slot"] < 128)]
            for e in enemies:
                enemy_n[e] += 1
            for it in fb:
                item_n[it] += 1
                for e in enemies:
                    pair[it][e] += 1
    return {"item_n": item_n, "pair": pair, "enemy_n": enemy_n, "total": total}


def explain(item, buy_time, team_adv, enemies, enemy_buys, heroes, lifts, item_names, components=frozenset(), duration=None,
            raw_parts=frozenset()):
    """raw_parts — базовые компоненты без своей активной способности (Hyperstone, Demon Edge...).
    Только про них имеет смысл писать «игра закончилась до сборки»."""
    """enemies: список hero_id врагов; enemy_buys: {hero_id: {item: time}}; heroes: константы OpenDota."""
    names = {e: heroes[str(e)]["localized_name"] for e in enemies if str(e) in heroes}
    short = {e: heroes[str(e)]["name"].replace("npc_dota_hero_", "") for e in enemies if str(e) in heroes}
    reasons = []
    rule = RULES.get(item)
    if rule:
        tags, eitems, why = rule
        hit = []
        for t in tags:
            label, pool = TAGS[t]
            hs = [names[e] for e in enemies if short.get(e) in pool]
            if hs:
                hit.append((len(hs), f"против {', '.join(hs)} ({label})"))
        for key in eitems:
            pool, label = ENEMY_ITEMS[key]
            got = []
            for e in enemies:
                for it, t in (enemy_buys.get(e) or {}).items():
                    if it in pool and t <= buy_time + 30:
                        got.append(f"{names.get(e, '?')}: {item_names.get(it, it)}")
            if got:
                hit.append((len(got) + 1, f"у врага {label}: {', '.join(got[:3])}"))
        if hit:
            hit.sort(key=lambda x: -x[0])
            reasons.append(f"{why} — " + "; ".join(h for _, h in hit[:2]))
    if item in ("gem", "dust", "ward_sentry") and not reasons:
        return "скорее для девардинга и контроля обзора: невидимых героев у врага нет"
    if item == "gem" and reasons:
        reasons[0] += " (заодно девардинг)"
    if not reasons and item in GENERAL:
        reasons.append(GENERAL[item])
    if not reasons and item in raw_parts and item not in RULES and duration and buy_time >= duration - 480:
        return "компонент: скорее всего игра закончилась до сборки большого предмета"
    if not reasons and lifts:
        n_item = lifts["item_n"].get(item, 0)
        if n_item >= 8:
            base = n_item / max(lifts["total"], 1)
            best = []
            for e in enemies:
                ne = lifts["enemy_n"].get(e, 0)
                c = lifts["pair"][item].get(e, 0)
                if ne >= 15 and c >= 4:
                    lift = (c / ne) / base
                    if lift >= 2.0:
                        best.append((lift, names.get(e, "?")))
            if best:
                best.sort(reverse=True)
                reasons.append("в про-матчах его заметно чаще берут против " +
                               ", ".join(f"{n} (×{lf:.1f})" for lf, n in best[:2]))
    minute = max(0, buy_time // 60)
    adv = team_adv[minute] if minute < len(team_adv) else (team_adv[-1] if team_adv else None)
    if adv is not None:
        if adv >= 8000 and (item in GREEDY or not reasons):
            reasons.append(f"жадный выбор: команда впереди на {adv / 1000:+.1f}k")
        elif adv <= -8000 and not reasons:
            reasons.append(f"оборонительный выбор: команда позади на {adv / 1000:+.1f}k")
    return "; ".join(reasons) or None
