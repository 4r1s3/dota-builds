"use strict";
const $ = s => document.querySelector(s);
const POS = {1: "Pos 1 · керри", 2: "Pos 2 · мид", 3: "Pos 3 · оффлейн", 4: "Pos 4 · роумер", 5: "Pos 5 · саппорт"};
const MIN_SAMPLE = 8;

// номер очка → уровень героя: на 10-м уровне два очка (способность + талант), на 16, 17, 19, 21–24 очков нет
const PT_LEVEL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 11, 12, 13, 14, 15, 18, 20, 25];
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
  }).join("") || `<div class="empty-msg">Героев не нашлось</div>`;
  const pl = filterPlayers($("#q").value).slice(0, 12);
  $("#found").innerHTML = pl.length ? `<h2>Про-игроки</h2><div class="pgrid">${pl.map(playerCard).join("")}</div>` : "";
  $("#found").hidden = !pl.length;
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
  setView("card");
  const card = $("#card");

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

  const skills = skillRow(d);
  const talents = talentRows(d);
  const nm = key => esc((DB.items[key] || {}).name || key);
  const icon = key => (DB.items[key] || {}).img ? `<img loading="lazy" src="${DB.items[key].img}" alt="">` : "";
  const bar = x => `<div class="pbar"><i style="width:${Math.round(x * 100)}%"></i></div>`;
  const start = d.start.map(s => `<div class="ic" data-tip="${nm(s.key)} — берут в ${pct(s.share)} игр">
      <div class="pic">${icon(s.key)}${s.count > 1 ? `<span class="cnt">×${s.count}</span>` : ""}</div>
      <div class="nm">${nm(s.key)}</div>${bar(s.share)}<div class="sub">${pct(s.share)} игр</div></div>`).join("");
  const vrow = its => its.map(i => `<div class="vi" data-tip="${nm(i.key)}${i.count > 1 ? " ×" + i.count : ""}">${icon(i.key)}${i.count > 1 ? `<span class="cnt">×${i.count}</span>` : ""}<div class="vn">${nm(i.key)}</div></div>`).join("");
  const setCard = (title, its, meta, players, cls = "", v = null) => `<div class="variant ${cls}">
      <div class="vt">${title}</div>
      <div class="vsub">До горна</div>
      <div class="vitems">${vrow(its)}</div>
      ${v && v.after && v.after.length ? `<div class="vsub after" data-tip="Самый частый вариант у этого закупа: в ${v.afterGames} из ${v.games} игр. Обычно приносит курьер, пока герой идёт в лайн">Докупают в первую минуту после горна <small>${v.afterGames} из ${v.games}</small></div>
      <div class="vitems">${vrow(v.after)}</div>` : ""}
      <div class="vm">${meta}</div>${players && players.length ? `<div class="vp">Брали: ${players.map(esc).join(", ")}</div>` : ""}</div>`;
  const cost = its => its.reduce((s, i) => s + ((DB.items[i.key] || {}).cost || 0) * i.count, 0);
  const sets = (raw.startSets || []);
  const setMeta = v => `<b>${v.games}</b> из ${raw.games} игр (${pct(v.share)}) · винрейт <b>${pct(v.wr)}</b> · ${v.cost} из 600 золота`;
  let variants;
  if (useImm && raw.imm.startSet && raw.imm.startSet.length) {
    variants = setCard("Основной закуп", raw.imm.startSet,
      `то, что берут больше чем в половине из ${raw.imm.games.toLocaleString("ru-RU")} игр Divine/Immortal · ${cost(raw.imm.startSet)} из 600 золота`, null, "main")
      + (sets[0] ? setCard("Ситуативный — как берут про-игроки", sets[0].items, setMeta(sets[0]), sets[0].players, "", sets[0]) : "");
  } else {
    variants = sets.slice(0, 2).map((v, i) => setCard(i ? "Ситуативный" : "Основной закуп", v.items, setMeta(v), v.players, i ? "" : "main", v)).join("");
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
  const games = list.map(g => gameCard(g)).join("");

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
  go(`#h${id}`);
}
function go(hash) {
  history.pushState({app: 1}, "", hash || location.pathname + location.search);
  route();
}
// все внутренние ссылки (#...) и карточки игроков — через историю
document.addEventListener("click", e => {
  const a = e.target.closest("a[href^='#']");
  const card = e.target.closest(".pcard");
  if (a) { e.preventDefault(); return go(a.getAttribute("href") === "#" ? "" : a.getAttribute("href")); }
  if (card) go(`#p${card.dataset.player}`);
});
function goGrid() {
  if (history.state && history.state.app) history.back();
  else { history.replaceState(null, "", location.pathname + location.search); route(); }
  $("#q").focus();
  $("#q").select();
}

function route() {
  const h = location.hash;
  let m;
  if ((m = h.match(/^#h(\d+)(?:-(\d))?$/))) return showHero(+m[1], m[2] ? +m[2] : null);
  if ((m = h.match(/^#p(\d+)(?:-h(\d+))?$/))) return showPlayer(+m[1], m[2] ? +m[2] : null);
  if ((m = h.match(/^#players(?:-(\d))?$/))) return showPlayers(m[1] ? +m[1] : 0);
  setView("heroes");
  renderGrid();
}


// ---------- прокачка и таланты (общие для героя и игрока)
// Каждое очко подписано уровнем героя, на котором его получили (на 10-м два очка, на 16–17 нет).
// Таланты — узкие метки на том месте, где их реально взяли, без своего номера в строке.
// cmp — прокачка для сравнения: отличающиеся очки подсвечиваются.
function skillRow(d, cmp) {
  const cells = [];
  d.skills.slice(0, PT_LEVEL.length).forEach((s, i) => {
    const lv = PT_LEVEL[i];
    if (s.startsWith("special_bonus")) {
      const row = d.talents.find(t => t.options.some(o => o.name === s));
      const tier = row ? row.level : lv;
      const right = row && row.options[0].name === s;
      const late = row && lv > tier ? `\nВзят на ${lv} уровне вместо ${tier}-го — очко на ${tier}-м ушло в способность` : "";
      cells.push(`<div class="tmark ${late ? "late" : ""}" data-tip="Талант ${tier}: ${esc(talentName(s))}${lv === 10 ? "\nНа 10 уровне дают 2 очка — способность и талант" : ""}${late}">${right ? "▶" : "◀"}<small>${tier}</small></div>`);
      return;
    }
    const a = DB.abilities[s] || {name: s};
    const other = cmp && cmp[i] && cmp[i] !== s ? cmp[i] : null;
    const otherName = other ? (other.startsWith("special_bonus") ? "талант" : (DB.abilities[other] || {name: other}).name) : "";
    cells.push(`<div class="sk ${other ? "diff" : ""}" data-tip="${esc(a.name)} — ${lv} уровень${lv === 10 ? " (на 10-м дают 2 очка)" : ""}${other ? "\nОбычно на этом месте: " + esc(otherName) : ""}">${a.img ? `<img loading="lazy" src="${a.img}" alt="">` : ""}${lv}</div>`);
  });
  return cells.join("");
}
function talentRows(d) {
  return [...d.talents].reverse().map(t => {
    const [R, L] = t.options; // в игре первый талант уровня — справа
    const opt = o => !o ? "<div></div>" : `<div class="topt ${t.sample && o.pick >= .5 ? "pick" : ""}">
      <span class="pc" ${o.wr != null ? `data-tip="винрейт ${pct(o.wr)}"` : ""}>${t.sample ? pct(o.pick) : "–"}</span>${esc(talentName(o.name))}
      <div class="bar" style="width:${o.pick * 100}%"></div></div>`;
    return `<div class="trow">${opt(L)}<div class="lv" ${t.fromPro ? 'data-tip="По этому уровню у STRATZ нет полных данных — показаны про-матчи"' : ""}>${t.level}${t.fromPro ? "*" : ""}</div>${opt(R)}</div>`;
  }).join("");
}

// ---------- карточка матча (общая для героя и игрока)
function heroIcon(id, cls = "hi") {
  const h = HERO_BY_ID[id];
  return h ? `<img class="${cls}" loading="lazy" src="${h.img}" alt="" data-tip="${esc(h.name)}">` : "";
}
function gameCard(g, opts = {}) {
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
  const h = HERO_BY_ID[g.hero];
  const who = opts.showHero && h
    ? `<a class="ghero" href="#h${h.id}${g.pos ? "-" + g.pos : ""}">${heroIcon(h.id, "hb")}<span>${esc(h.name)}${g.pos ? ` <small>pos ${g.pos}</small>` : ""}</span></a>`
    : `<span class="pl">${esc(g.player)}</span>`;
  return `<div class="game"><div class="ghead">
    ${who}${g.src === "pub" ? `<span class="pub" data-tip="Рейтинговая игра Immortal${g.rank ? ", ранг " + g.rank : ""}">паб Immortal</span>` : ""}
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
      <div class="team"><span>С кем</span><div>${(g.allies || []).map(id => heroIcon(id)).join("")}</div></div>
      <div class="team vs"><span>Против</span><div>${g.enemies.map(id => heroIcon(id)).join("")}</div></div></div>` : ""}
  </div>${whys ? `<div class="whys">${whys}</div>` : ""}</div>`;
}

// ---------- про-игроки
let PLAYERS = null;
const pcache = {};
async function loadPlayers() {
  if (!PLAYERS) {
    const r = await fetch(`data/players.json?v=${DB.meta.updated}`);
    PLAYERS = r.ok ? await r.json() : [];
  }
  return PLAYERS;
}
function filterPlayers(q) {
  q = q.trim().toLowerCase();
  if (!q || !PLAYERS) return [];
  const qs = [q];
  if (/[а-я]/.test(q) && typeof fromRuLayout === "function") qs.push(fromRuLayout(q));
  const starts = [], incl = [];
  for (const p of PLAYERS) {
    const n = (p.name || "").toLowerCase(), t = (p.team || "").toLowerCase();
    if (qs.some(x => n.startsWith(x))) starts.push(p);
    else if (qs.some(x => x.length > 1 && (n.includes(x) || t.includes(x)))) incl.push(p);
  }
  return [...starts, ...incl];
}
const wr = (w, n) => n ? Math.round(w / n * 100) + "%" : "–";
function playerCard(p) {
  const hs = p.heroes.slice(0, 6).map(h => `<a class="phero" href="#p${p.id}-h${h.id}" data-tip="${esc((HERO_BY_ID[h.id] || {}).name || "")}: ${h.games} игр, винрейт ${wr(h.wins, h.games)}">
      ${heroIcon(h.id, "pi")}<span>${h.games} · <b class="${h.wins / h.games >= .5 ? "g" : "r"}">${wr(h.wins, h.games)}</b></span></a>`).join("");
  return `<div class="pcard" data-player="${p.id}">
    <div class="ptop"><div><div class="pname">${esc(p.name)}</div><div class="pteam">${esc(p.team || "без команды")}</div></div>
      <div class="ppos">${p.pos ? "Pos " + p.pos : ""}</div></div>
    <div class="pstat"><b>${p.games}</b> игр · винрейт <b class="${p.wins / p.games >= .5 ? "g" : "r"}">${wr(p.wins, p.games)}</b> · ${ago(p.last)}</div>
    <div class="pheroes">${hs}</div></div>`;
}
async function showPlayers(pos) {
  await loadPlayers();
  setView("players");
  const tabs = [0, 1, 2, 3, 4, 5].map(p => {
    const n = p ? PLAYERS.filter(x => x.pos === p).length : PLAYERS.length;
    return `<button class="tab ${p === (pos || 0) ? "on" : ""}" data-ppos="${p}">${p ? POS[p] : "Все"} <small>${n}</small></button>`;
  }).join("");
  const q = $("#q").value.trim();
  let list = q ? filterPlayers(q) : PLAYERS;
  if (pos) list = list.filter(x => x.pos === pos);
  $("#players").innerHTML = `<div class="tabs">${tabs}</div>
    <div class="legend">Про-игроки из матчей за последние ${DB.meta.days} дн. Нажми на игрока — история матчей, на героя — матчи только на нём.</div>
    <div class="pgrid">${list.map(playerCard).join("") || '<div class="empty-msg">Никого не нашлось</div>'}</div>`;
  $("#players").querySelectorAll("[data-ppos]").forEach(b => b.onclick = () => {
    const p = +b.dataset.ppos;
    history.replaceState(history.state, "", p ? `#players-${p}` : "#players");
    showPlayers(p);
  });
}
async function showPlayer(id, heroId) {
  if (!pcache[id]) {
    const r = await fetch(`data/players/${id}.json?v=${DB.meta.updated}`);
    pcache[id] = r.ok ? await r.json() : null;
  }
  const p = pcache[id];
  setView("card");
  const card = $("#card");
  if (!p) { card.innerHTML = `<div class="empty-msg">Игрок не найден</div>`; return; }
  const list = heroId ? p.matches.filter(m => m.hero === heroId) : p.matches;
  const chips = [`<a class="hchip ${heroId ? "" : "on"}" href="#p${p.id}">Все герои <small>${p.games}</small></a>`]
    .concat(p.heroes.map(h => `<a class="hchip ${h.id === heroId ? "on" : ""}" href="#p${p.id}-h${h.id}">${heroIcon(h.id, "hc")}${esc((HERO_BY_ID[h.id] || {}).name || "")} <small>${h.games} · ${wr(h.wins, h.games)}</small></a>`)).join("");
  const posInfo = Object.entries(p.posCount || {}).sort((a, b) => b[1] - a[1]).map(([k2, v]) => `pos ${k2}: ${v}`).join(", ");
  const build = heroId && p.builds ? p.builds[heroId] : null;
  let buildHtml = "";
  if (build) {
    const hero = HERO_BY_ID[heroId] || {name: ""};
    const general = await loadHero(heroId);
    const gp = general.positions && general.positions[build.pos];
    const nm = key => esc((DB.items[key] || {}).name || key);
    const icon = key => (DB.items[key] || {}).img ? `<img loading="lazy" src="${DB.items[key].img}" alt="">` : "";
    const itemCard = (i, extra = "") => `<div class="ic" data-tip="${nm(i.key)}: ${pct(i.share)} его игр${i.time != null ? ", ~" + mmss(i.time) : ""}, винрейт ${pct(i.wr)}${extra}">
      <div class="pic">${icon(i.key)}</div><div class="nm">${nm(i.key)}</div>${i.time != null ? `<div class="when">~${Math.round(i.time / 60)} мин</div>` : ""}
      <div class="pbar"><i style="width:${Math.round(i.share * 100)}%"></i></div><div class="sub">${pct(i.share)} игр</div></div>`;
    const sig = build.signature.map(i => `<div class="sigrow">${icon(i.key)}<div><b>${nm(i.key)}</b>
      <div class="stats">у него в <b>${pct(i.share)}</b> игр (${i.n}) · у остальных на pos ${build.pos} — <b>${pct(i.general)}</b> · винрейт с ним <b class="${i.wr >= .5 ? "g" : "r"}">${pct(i.wr)}</b>${i.time != null ? " · ~" + mmss(i.time) : ""}</div></div></div>`).join("");
    const st = build.start;
    const vrow = its => its.map(i => `<div class="vi" data-tip="${nm(i.key)}${i.count > 1 ? " ×" + i.count : ""}">${icon(i.key)}${i.count > 1 ? `<span class="cnt">×${i.count}</span>` : ""}<div class="vn">${nm(i.key)}</div></div>`).join("");
    const heroWr = gp ? gp.wr : null;
    buildHtml = `<div class="pbuild">
      <h2>${esc(p.name)} на ${esc(hero.name)}${build.pos ? " · pos " + build.pos : ""}</h2>
      <div class="stats"><b>${build.games}</b> игр · винрейт <b class="${build.wins / build.games >= .5 ? "g" : "r"}">${wr(build.wins, build.games)}</b>${heroWr != null ? ` · у всех про на этой позиции ${pct(heroWr)}` : ""}
        · <a href="#h${heroId}${build.pos ? "-" + build.pos : ""}">общий билд героя →</a></div>
      ${build.games < 3 ? `<div class="warn">Всего ${build.games} ${build.games === 1 ? "игра" : "игры"} — это скорее конкретные матчи, чем привычки игрока.</div>` : ""}
      ${sig ? `<h2>Особенности игрока</h2><div class="legend">Предметы, которые он берёт заметно чаще остальных про-игроков на этом герое и позиции</div><div class="sigs">${sig}</div>` : ""}
      <h2>Прокачка</h2>${gp && gp.skills.length ? `<div class="legend"><i class="dl"></i> — очко не так, как у большинства про-игроков (наведи, чтобы увидеть как обычно)</div>` : ""}
      <div class="skills">${skillRow(build, gp ? gp.skills : null)}</div>
      <h2>Таланты</h2><div class="talents">${talentRows(build)}</div>
      ${st ? `<h2>Стартовый закуп</h2><div class="variants"><div class="variant main"><div class="vsub">До горна</div><div class="vitems">${vrow(st.items)}</div>
        ${st.after.length ? `<div class="vsub after">Докупает в первую минуту <small>${st.afterGames} из ${st.games}</small></div><div class="vitems">${vrow(st.after)}</div>` : ""}
        <div class="vm"><b>${st.games}</b> из ${build.games} игр · ${st.cost} из 600 золота</div></div></div>` : ""}
      <h2>Что покупает — по порядку</h2><div class="items">${build.core.map(i => itemCard(i)).join("") || '<span class="stats">—</span>'}</div>
      ${build.situational.length ? `<h2>Иногда</h2><div class="items">${build.situational.map(i => itemCard(i)).join("")}</div>` : ""}
    </div>`;
  }
  card.innerHTML = `<div class="head"><button class="back">← Назад</button>
    <div><h1>${esc(p.name)}</h1><div class="stats">${esc(p.team || "без команды")} · <b>${p.games}</b> игр · винрейт <b>${wr(p.wins, p.games)}</b>${posInfo ? " · " + posInfo : ""}</div></div></div>
    <h2>Герои</h2><div class="hchips">${chips}</div>
    ${buildHtml}
    <h2>${heroId ? `Матчи на ${esc((HERO_BY_ID[heroId] || {}).name || "")}` : "Все матчи"} — от новых к старым <small class="stats">(${list.length})</small></h2>
    <div class="legend"><i></i> — предмет не из стандартного билда героя на этой позиции</div>
    <div class="pro">${list.map(g => gameCard(g, {showHero: true})).join("") || '<div class="empty-msg">Нет матчей</div>'}</div>`;
  card.querySelector(".back").onclick = goGrid;
  window.scrollTo(0, 0);
}
function setView(v) {
  $("#grid").hidden = v !== "heroes";
  $("#found").hidden = v !== "heroes" || !$("#found").innerHTML;
  $("#players").hidden = v !== "players";
  $("#card").hidden = v !== "card";
  const tab = v === "players" || /^#p\d/.test(location.hash) ? "players" : "heroes";
  document.querySelectorAll(".nav a").forEach(a => a.classList.toggle("on", a.dataset.nav === tab));
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
  loadPlayers().then(() => { if (!$("#grid").hidden) renderGrid(); });
  $("#q").addEventListener("input", () => {
    if (!$("#players").hidden) return showPlayers(+(location.hash.match(/-(\d)$/) || [0, 0])[1]);
    if ($("#grid").hidden) history.replaceState(null, "", location.pathname + location.search);
    route();
  });
  $("#q").addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const q = $("#q").value;
      const h = filterHeroes(q).find(h => Object.keys(h.positions).length) || filterHeroes(q)[0];
      const p = filterPlayers(q)[0];
      if (!$("#players").hidden && p) go(`#p${p.id}`);
      else if (h && q.trim()) openHero(h.id);
      else if (p) go(`#p${p.id}`);
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
