"use strict";
const $ = s => document.querySelector(s);
const POS = {1: "Pos 1 · керри", 2: "Pos 2 · мид", 3: "Pos 3 · оффлейн", 4: "Pos 4 · роумер", 5: "Pos 5 · саппорт"};
const MIN_SAMPLE = 8;
// номер очка → уровень героя (на 17, 19, 21–24 очков навыков нет)
const PT_LEVEL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 25];
let DB = null;
const HERO_BY_ID = {};
let SRC = (() => { try { return localStorage.getItem("src") || "imm"; } catch { return "imm"; } })();
const cache = {};

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const mmss = t => t == null ? "" : `${Math.floor(t / 60)}:${String(Math.abs(t) % 60).padStart(2, "0")}`;
const mins = t => t == null ? "" : `${Math.round(t / 60)}'`;
const pct = x => `${Math.round(x * 100)}%`;
const k = n => n == null ? "?" : (n >= 0 ? "+" : "−") + (Math.abs(n) / 1000).toFixed(1) + "k";
const ago = ts => {
  const d = Math.floor((Date.now() / 1000 - ts) / 86400);
  return d <= 0 ? "сегодня" : d === 1 ? "вчера" : `${d} дн. назад`;
};

function talentName(key) {
  const raw = DB.talents[key] || key;
  return raw.replace(/\{s:[^}]+\}/g, "?").replace(/\s+/g, " ");
}

// ---------- поиск
const aliasCache = {};
function aliases(h) {
  if (aliasCache[h.id]) return aliasCache[h.id];
  const words = h.name.toLowerCase().split(/[\s\-']+/).filter(Boolean);
  const ru = (typeof RU_NAMES !== "undefined" && RU_NAMES[h.short]) || "";
  const ruWords = ru.split(/\s+/).filter(Boolean);
  // русские названия из нескольких слов тоже ищутся целиком: «шадоу финд»
  const ruPhrases = [];
  for (let i = 0; i < ruWords.length - 1; i++) ruPhrases.push(ruWords[i] + " " + ruWords[i + 1]);
  return aliasCache[h.id] = [h.name.toLowerCase(), h.short, h.short.replace(/_/g, " "),
    words.map(w => w[0]).join(""), ...words, ...ruWords, ...ruPhrases];
}
function filterHeroes(q) {
  q = q.trim().toLowerCase().replace(/ё/g, "е");
  if (!q) return DB.heroes;
  // вариант запроса, если его набрали на русской раскладке вместо английской: «шщ» → «io»
  const qs = [q];
  if (/[а-я]/.test(q) && typeof fromRuLayout === "function") qs.push(fromRuLayout(q));
  const exact = [], starts = [], incl = [];
  for (const h of DB.heroes) {
    const al = aliases(h);
    if (qs.some(x => al.some(a => a === x))) exact.push(h);
    else if (qs.some(x => al.some(a => a.startsWith(x)))) starts.push(h);
    else if (qs.some(x => x.length > 2 && al.some(a => a.includes(x)))) incl.push(h);
  }
  return [...exact, ...starts, ...incl];
}
function renderGrid() {
  const list = filterHeroes($("#q").value);
  $("#grid").innerHTML = list.map((h, i) => {
    const has = Object.keys(h.positions).length;
    return `<div class="hero ${has ? "" : "nodata"} ${i === 0 && $("#q").value ? "sel" : ""}" data-id="${h.id}" title="${esc(h.name)}">
      <img loading="lazy" src="${h.img}" alt=""><div class="n">${esc(h.name)}</div></div>`;
  }).join("") || `<div class="empty-msg">Ничего не нашлось</div>`;
}

// ---------- карточка героя
async function loadHero(id) {
  if (!cache[id]) {
    const r = await fetch(`data/heroes/${id}.json?v=${DB.meta.updated}`);
    cache[id] = r.ok ? await r.json() : {id, positions: {}};
  }
  return cache[id];
}
function bestPos(h) {
  const e = Object.entries(SRC === "imm" && h.imm && Object.keys(h.imm).length ? h.imm : h.positions);
  return e.length ? +e.sort((a, b) => b[1] - a[1])[0][0] : 1;
}
function itemTile(key, extra = "", cls = "it", tip = "") {
  const it = DB.items[key] || {name: key};
  return `<div class="${cls}" data-tip="${esc(tip || it.name)}">${it.img ? `<img loading="lazy" src="${it.img}" alt="">` : ""}${extra}</div>`;
}

async function showHero(id, pos) {
  const hero = DB.heroes.find(h => h.id === id);
  if (!hero) return;
  const data = await loadHero(id);
  pos = pos && data.positions[pos] ? pos : bestPos(hero);
  const raw = data.positions[pos];
  const useImm = SRC === "imm" && raw && raw.imm;
  const d = raw && (useImm ? {
    ...raw, games: raw.imm.games, wr: raw.imm.wr, gpm: raw.gpm,
    start: raw.imm.start.length ? raw.imm.start : raw.start,
    core: raw.imm.core.length ? raw.imm.core : raw.core,
    situational: raw.imm.core.length ? raw.imm.situational : raw.situational,
    itemsFromPro: !raw.imm.core.length,
    talents: raw.talents.map((t, i) => {
      const it = raw.imm.talents[i + 1] || {};
      if (Object.keys(it).length < Math.min(2, t.options.length)) return {...t, fromPro: true};
      return {...t, sample: 1,
        options: t.options.map(o => ({...o, pick: (it[o.name] || {}).pick || 0, wr: (it[o.name] || {}).wr}))};
    }),
  } : raw);
  history.replaceState(history.state, "", `#h${id}-${pos}`);
  $("#grid").hidden = true;
  const card = $("#card");
  card.hidden = false;

  const tabs = [1, 2, 3, 4, 5].map(p => {
    const n = hero.positions[p] || 0, im = (hero.imm || {})[p] || 0;
    const has = n || im;
    const cnt = SRC === "imm" && hero.imm ? (im ? `${(im / 1000).toFixed(1)}k` : "0") : n;
    return `<button class="tab ${p === pos ? "on" : ""} ${has ? "" : "empty"}" ${has ? `data-pos="${p}"` : "disabled"}>${POS[p]} <small>${cnt}</small></button>`;
  }).join("");
  const anyImm = hero.imm && Object.keys(hero.imm).length;
  const srcSw = anyImm ? `<div class="src">Статистика:
    <button class="sbtn ${SRC === "imm" ? "on" : ""}" data-src="imm">Divine/Immortal пабы</button>
    <button class="sbtn ${SRC === "pro" ? "on" : ""}" data-src="pro">Про-матчи</button></div>` : "";

  if (!d) {
    card.innerHTML = head(hero, null) + srcSw + `<div class="tabs">${tabs}</div><div class="empty-msg">Нет про-матчей на этом герое за последние ${DB.meta.days} дн.</div>`;
    return bind(hero);
  }

  // Способности — по своим уровням, таланты — узкими метками на 10/15/20/25 (без номера в строке)
  const abil = d.skills.filter(s => !s.startsWith("special_bonus"));
  const chosen = {};
  d.skills.filter(s => s.startsWith("special_bonus")).forEach(s => {
    const row = d.talents.find(t => t.options.some(o => o.name === s));
    if (row) chosen[row.level] = s;
  });
  d.talents.forEach(t => {
    if (!chosen[t.level] && t.sample) chosen[t.level] = [...t.options].sort((a, b) => b.pick - a.pick)[0].name;
  });
  const ABIL_LV = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 16, 18];
  const cells = [];
  const marker = lv => {
    const s = chosen[lv];
    if (!s) return;
    const row = d.talents.find(t => t.level === lv);
    const right = row && row.options[0].name === s;
    cells.push(`<div class="tmark" data-tip="Талант ${lv}: ${esc(talentName(s))}">${right ? "▶" : "◀"}<small>${lv}</small></div>`);
  };
  abil.slice(0, ABIL_LV.length).forEach((s, i) => {
    const lv = ABIL_LV[i];
    if (lv === 11) marker(10);
    if (lv === 16) marker(15);
    const a = DB.abilities[s] || {name: s};
    cells.push(`<div class="sk" data-tip="${esc(a.name)} — ${lv} уровень">${a.img ? `<img loading="lazy" src="${a.img}" alt="">` : ""}${lv}</div>`);
  });
  if (abil.length >= 15) { marker(20); marker(25); }
  const skills = cells.join("");

  const talents = [...d.talents].reverse().map(t => {
    const [R, L] = t.options; // в игре первый талант уровня — справа
    const opt = o => !o ? "<div></div>" : `<div class="topt ${t.sample && o.pick >= .5 ? "pick" : ""}">
      <span class="pc" ${o.wr != null ? `data-tip="винрейт ${pct(o.wr)}"` : ""}>${t.sample ? pct(o.pick) : "–"}</span>${esc(talentName(o.name))}
      <div class="bar" style="width:${o.pick * 100}%"></div></div>`;
    return `<div class="trow">${opt(L)}<div class="lv" ${t.fromPro ? 'data-tip="По этому уровню у STRATZ нет полных данных — показаны про-матчи"' : ""}>${t.level}${t.fromPro ? "*" : ""}</div>${opt(R)}</div>`;
  }).join("");

  const nm = key => esc((DB.items[key] || {}).name || key);
  const icon = key => (DB.items[key] || {}).img ? `<img loading="lazy" src="${DB.items[key].img}" alt="">` : "";
  const bar = x => `<div class="pbar"><i style="width:${Math.round(x * 100)}%"></i></div>`;
  const start = d.start.map(s => `<div class="ic" data-tip="${nm(s.key)} — берут в ${pct(s.share)} игр">
      <div class="pic">${icon(s.key)}${s.count > 1 ? `<span class="cnt">×${s.count}</span>` : ""}</div>
      <div class="nm">${nm(s.key)}</div>${bar(s.share)}<div class="sub">${pct(s.share)} игр</div></div>`).join("");
  const setCard = (title, its, meta, players, cls = "") => `<div class="variant ${cls}">
      <div class="vt">${title}</div>
      <div class="vitems">${its.map(i => `<div class="vi" data-tip="${nm(i.key)}${i.count > 1 ? " ×" + i.count : ""}">${icon(i.key)}${i.count > 1 ? `<span class="cnt">×${i.count}</span>` : ""}<div class="vn">${nm(i.key)}</div></div>`).join("")}</div>
      <div class="vm">${meta}</div>${players && players.length ? `<div class="vp">Брали: ${players.map(esc).join(", ")}</div>` : ""}</div>`;
  const cost = its => its.reduce((s, i) => s + ((DB.items[i.key] || {}).cost || 0) * i.count, 0);
  const sets = (raw.startSets || []);
  const setMeta = v => `<b>${v.games}</b> из ${raw.games} игр (${pct(v.share)}) · винрейт <b>${pct(v.wr)}</b> · ≈${v.cost} золота`;
  let variants;
  if (useImm && raw.imm.startSet && raw.imm.startSet.length) {
    variants = setCard("Основной закуп", raw.imm.startSet,
      `то, что берут больше чем в половине из ${raw.imm.games.toLocaleString("ru-RU")} игр Divine/Immortal · ≈${cost(raw.imm.startSet)} золота`, null, "main")
      + (sets[0] ? setCard("Ситуативный — как берут про-игроки", sets[0].items, setMeta(sets[0]), sets[0].players) : "");
  } else {
    variants = sets.slice(0, 2).map((v, i) => setCard(i ? "Ситуативный" : "Основной закуп", v.items, setMeta(v), v.players, i ? "" : "main")).join("");
  }
  const core = d.core.map((c, i) => `<div class="ic core" data-tip="${nm(c.key)}: обычно покупают на ${mmss(c.time)}, берут в ${pct(c.share)} игр, винрейт с ним ${pct(c.wr)}">
      <div class="pic">${icon(c.key)}<span class="step">${i + 1}</span></div>
      <div class="nm">${nm(c.key)}</div><div class="when">~${Math.round(c.time / 60)} мин</div>${bar(c.share)}<div class="sub">${pct(c.share)} игр</div>
      ${c.alt ? `<div class="alt" data-tip="Вместо ${nm(c.key)} в этом месте берут ${nm(c.alt.key)}: ${pct(c.alt.share)} игр, ~${mmss(c.alt.time)}, винрейт ${pct(c.alt.wr)}. Вместе их почти не покупают — выбирай по игре">
        <span>или</span><div class="pic">${icon(c.alt.key)}</div><div class="nm">${nm(c.alt.key)}</div><div class="sub">${pct(c.alt.share)} игр</div></div>` : ""}</div>`).join("");
  const sit = d.situational.map(c => `<div class="ic" data-tip="${nm(c.key)}: ~${mmss(c.time)}, берут в ${pct(c.share)} игр, винрейт ${pct(c.wr)} (${c.n} игр)">
      <div class="pic">${icon(c.key)}</div><div class="nm">${nm(c.key)}</div>${bar(c.share)}<div class="sub">${pct(c.share)} игр · ~${Math.round(c.time / 60)} мин</div></div>`).join("");

  const th = DB.meta.thresholds;
  const list = useImm ? (raw.pubs || []) : (raw.pro || []);
  const heroIcon = id => {
    const h = HERO_BY_ID[id];
    return h ? `<img class="hi" loading="lazy" src="${h.img}" alt="" data-tip="${esc(h.name)}">` : "";
  };
  const games = list.map(g => {
    let badge = "";
    if (g.flag === "stomp") badge = `<span class="badge stomp" data-tip="Перевес команды до ${k(g.maxAdv)} или GPM сильно выше обычного. Билд мог быть «жадным» — повторять только при таком же ходе игры">Игра шла очень хорошо · ${k(g.maxAdv)}</span>`;
    if (g.flag === "hard") badge = `<span class="badge hard" data-tip="Команда отставала до ${k(g.minAdv)}. Билд мог быть оборонительным">Тяжёлая игра · ${k(g.minAdv)}</span>`;
    const tile = i => itemTile(i.key, `<span class="gt">${mmss(i.time)}</span>`, "gi" + (i.odd ? " odd" : ""),
      `${(DB.items[i.key] || {}).name} — куплен на ${mmss(i.time)}, перевес команды ${k(i.adv)}${i.odd ? " · НЕ из стандартного билда" : ""}${i.why ? "\nПочему: " + i.why : ""}`);
    const phases = [["Лайн", "0–10 мин", 0, 600], ["Мидгейм", "10–25 мин", 600, 1500], ["Лейт", "25+ мин", 1500, 1e9]]
      .map(([name, range, a, b]) => {
        const list = g.items.filter(i => i.time >= a && i.time < b);
        return list.length ? `<div class="phase"><div class="ph">${name} <small>${range}</small></div><div class="gitems">${list.map(tile).join("")}</div></div>` : "";
      }).join("");
    const whys = g.items.filter(i => i.odd && i.why).map(i => `<div class="why"><b>${esc((DB.items[i.key] || {}).name || i.key)}</b> <span class="t">на ${mmss(i.time)}</span> — ${esc(i.why)}</div>`).join("");
    const chip = (label, val, tip) => `<span class="chip" ${tip ? `data-tip="${tip}"` : ""}>${label ? `<i>${label}</i>` : ""}${val}</span>`;
    return `<div class="game"><div class="ghead">
      <span class="pl">${esc(g.player)}</span>${g.src === "pub" ? `<span class="pub" data-tip="Рейтинговая игра Immortal${g.rank ? ", ранг " + g.rank : ""}">паб Immortal</span>` : ""}
      <span class="res ${g.win ? "w" : "l"}">${g.win ? "Победа" : "Поражение"}</span>
      ${badge}
      <span class="links"><a href="https://www.opendota.com/matches/${g.match}" target="_blank" rel="noopener">OpenDota</a>
      <a href="https://stratz.com/matches/${g.match}" target="_blank" rel="noopener">STRATZ</a></span>
    </div>
    <div class="chips">
      ${chip("K / D / A", `<b class="kk">${g.k}</b> / <b class="dd">${g.d}</b> / <b>${g.a}</b>`, "Убийства / смерти / помощь")}
      ${chip("GPM", `<b>${g.gpm}</b>`, "Золото в минуту")}
      ${chip("Длительность", `<b>${mmss(g.dur)}</b>`)}
      ${chip("", `${esc(g.league || "")} · ${ago(g.date)}`)}
    </div>
    <div class="gbody"><div class="phases">${phases}</div>
      ${g.enemies && g.enemies.length ? `<div class="teams">
        <div class="team"><span>С кем</span><div>${(g.allies || []).map(heroIcon).join("")}</div></div>
        <div class="team vs"><span>Против</span><div>${g.enemies.map(heroIcon).join("")}</div></div></div>` : ""}
    </div>${whys ? `<div class="whys">${whys}</div>` : ""}</div>`;
  }).join("");

  const maxOrder = useImm && raw.imm.maxOrder.length ? `<h2>Что качать в первую очередь (Immortal)</h2><div class="maxo">${raw.imm.maxOrder.map((m, i) => {
      const a = DB.abilities[m.name] || {name: m.name};
      return (i ? '<span class="arrow">›</span>' : "") + `<div class="sk" data-tip="${esc(a.name)} — вкачивают до максимума ~ к ${m.level} уровню">${a.img ? `<img loading="lazy" src="${a.img}" alt="">` : ""}${esc(a.name)}<br><b>макс к ${m.level} ур.</b></div>`;
    }).join("")}</div>` : "";
  card.innerHTML = head(hero, d, useImm) + srcSw + `<div class="tabs">${tabs}</div>
    ${!useImm && d.games - (d.pubGames || 0) < MIN_SAMPLE ? `<div class="warn">Мало про-игр на этой позиции (${d.games - (d.pubGames || 0)})${d.pubGames ? `, поэтому добавлены ${d.pubGames} игр из Immortal-пабов` : ""}. Смотри на конкретные матчи ниже, статистика может быть случайной.</div>` : ""}
    ${maxOrder}
    <h2>Прокачка по уровням${useImm ? " (по про-игрокам)" : ""}</h2><div class="skills">${skills || '<span class="stats">Нет про-игр на этой позиции</span>'}</div>
    <h2>Таланты</h2><div class="talents">${talents}</div>
    <h2>Стартовый закуп — готовые варианты</h2>
    <div class="variants">${variants || '<span class="stats">Нет данных</span>'}</div>
    <div class="subh">Как часто берут каждый предмет на старте${useImm && raw.imm.start.length ? " (Divine/Immortal)" : ""}</div>
    <div class="items">${start || '<span class="stats">—</span>'}</div>
    <h2>Основной билд — по порядку покупки${d.itemsFromPro ? " (про-матчи)" : ""}</h2><div class="items">${core || '<span class="stats">—</span>'}</div>
    <h2>Ситуативные предметы — по популярности${d.itemsFromPro ? " (про-матчи)" : ""}</h2><div class="items">${sit || '<span class="stats">—</span>'}</div>
    <h2>${useImm ? "Игры Immortal-пабов" : "Про-игры"}</h2>
    <div class="legend"><i></i> — предмет не из стандартного билда, под игрой написано почему · порог «игра шла очень хорошо»: ${k(th.stompAdv)} к ${th.stompMinute}-й минуте</div>
    <div class="pro">${games || `<div class="stats">${useImm ? "Пабов на этой позиции пока нет — они докачиваются каждую ночь. Переключись на «Про-матчи»." : "Про-игр на этой позиции нет. Переключись на «Divine/Immortal пабы»."}</div>`}</div>`;
  bind(hero);
  window.scrollTo(0, 0);
}
function head(hero, d, imm) {
  return `<div class="head"><button class="back">← Герои</button><img src="${hero.img}" alt="">
    <div><h1>${esc(hero.name)}</h1>${d ? `<div class="stats"><b>${d.games.toLocaleString("ru-RU")}</b> ${imm ? "игр Divine/Immortal" : d.pubGames ? `игр (${d.games - d.pubGames} про + ${d.pubGames} Immortal-пабов)` : "про-игр"} · винрейт <b>${pct(d.wr)}</b>${!imm && d.gpm ? ` · GPM <b>${d.gpm}</b>` : ""}</div>` : ""}</div></div>`;
}
function bind(hero) {
  $("#card").querySelectorAll(".tab[data-pos]").forEach(b => b.onclick = () => showHero(hero.id, +b.dataset.pos));
  $("#card").querySelectorAll(".sbtn").forEach(b => b.onclick = () => {
    SRC = b.dataset.src;
    try { localStorage.setItem("src", SRC); } catch {}
    const m = location.hash.match(/^#h(\d+)-(\d)$/);
    showHero(hero.id, m ? +m[2] : null);
  });
  $("#card .back").onclick = goGrid;
}

// Навигация через историю браузера: «назад» (в т.ч. кнопка мыши 4) возвращает на предыдущую страницу
function openHero(id) {
  history.pushState({app: 1}, "", `#h${id}`);
  showHero(id);
}
function goGrid() {
  if (history.state && history.state.app) history.back();
  else { history.replaceState(null, "", location.pathname + location.search); route(); }
  $("#q").focus();
  $("#q").select();
}

function route() {
  const m = location.hash.match(/^#h(\d+)(?:-(\d))?$/);
  if (m) return showHero(+m[1], m[2] ? +m[2] : null);
  $("#card").hidden = true;
  $("#grid").hidden = false;
  renderGrid();
}

// ---------- подсказки
document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-tip]");
  const tip = $("#tip");
  if (!el) return tip.hidden = true;
  tip.textContent = el.dataset.tip;
  tip.hidden = false;
});
document.addEventListener("mousemove", e => {
  const tip = $("#tip");
  if (tip.hidden) return;
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px";
  tip.style.top = (e.clientY + 16) + "px";
});

// подсказки по нажатию (телефон)
document.addEventListener("click", e => {
  const el = e.target.closest("[data-tip]");
  if (!el || !matchMedia("(hover: none)").matches) return;
  const tip = $("#tip"), r = el.getBoundingClientRect();
  tip.textContent = el.dataset.tip;
  tip.hidden = false;
  tip.style.left = Math.max(8, Math.min(r.left, innerWidth - tip.offsetWidth - 8)) + "px";
  tip.style.top = (r.bottom + 6) + "px";
  clearTimeout(window.__tipT);
  window.__tipT = setTimeout(() => tip.hidden = true, 3000);
});

// ---------- старт
(async () => {
  DB = await (await fetch("data/index.json", {cache: "no-cache"})).json();
  DB.heroes.forEach(h => HERO_BY_ID[h.id] = h);
  const m = DB.meta;
  $("#meta").innerHTML = `Патч ${esc(m.patch)} · ${m.matches} про-матчей за ${m.days} дн.${m.stratz ? " + Immortal (STRATZ)" : ""}<br>обновлено ${new Date(m.updated * 1000).toLocaleString("ru-RU")}`;
  $("#q").addEventListener("input", () => {
    if ($("#grid").hidden) history.replaceState(null, "", location.pathname + location.search);
    route();
  });
  $("#q").addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const h = filterHeroes($("#q").value).find(h => Object.keys(h.positions).length) || filterHeroes($("#q").value)[0];
      if (h) openHero(h.id);
    }
  });
  $("#grid").addEventListener("click", e => {
    const el = e.target.closest(".hero");
    if (el) openHero(+el.dataset.id);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !$("#card").hidden) goGrid();
    else if (e.key === "/" && document.activeElement !== $("#q")) { e.preventDefault(); $("#q").focus(); $("#q").select(); }
  });
  window.addEventListener("popstate", route);
  route();
})();
