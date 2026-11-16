"use strict";
const $ = s => document.querySelector(s);
const POS = {1: "Pos 1 · керри", 2: "Pos 2 · мид", 3: "Pos 3 · оффлейн", 4: "Pos 4 · роумер", 5: "Pos 5 · саппорт"};
const MIN_SAMPLE = 8;
let DB = null;
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
function aliases(h) {
  const words = h.name.toLowerCase().split(/[\s\-']+/).filter(Boolean);
  return [h.name.toLowerCase(), h.short, words.map(w => w[0]).join(""), ...words];
}
function filterHeroes(q) {
  q = q.trim().toLowerCase();
  if (!q) return DB.heroes;
  const exact = [], starts = [], incl = [];
  for (const h of DB.heroes) {
    const al = aliases(h);
    if (al.some(a => a === q)) exact.push(h);
    else if (al.some(a => a.startsWith(q))) starts.push(h);
    else if (al.some(a => a.includes(q))) incl.push(h);
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
    const r = await fetch(`data/heroes/${id}.json`);
    cache[id] = r.ok ? await r.json() : {id, positions: {}};
  }
  return cache[id];
}
function bestPos(h) {
  const e = Object.entries(h.positions);
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
  const d = data.positions[pos];
  history.replaceState(null, "", `#h${id}-${pos}`);
  $("#grid").hidden = true;
  const card = $("#card");
  card.hidden = false;

  const tabs = [1, 2, 3, 4, 5].map(p => {
    const n = hero.positions[p];
    return `<button class="tab ${p === pos ? "on" : ""} ${n ? "" : "empty"}" ${n ? `data-pos="${p}"` : "disabled"}>${POS[p]} <small>${n || 0}</small></button>`;
  }).join("");

  if (!d) {
    card.innerHTML = head(hero, null) + `<div class="tabs">${tabs}</div><div class="empty-msg">Нет про-матчей на этом герое за последние ${DB.meta.days} дн.</div>`;
    return bind(hero);
  }

  const skills = d.skills.map((s, i) => {
    if (s.startsWith("special_bonus")) {
      const row = d.talents.find(t => t.options.some(o => o.name === s));
      const right = row && row.options[0].name === s;
      return `<div class="sk" data-tip="Талант ${row ? row.level : ""}: ${esc(talentName(s))}"><div class="tl">${right ? "▶" : "◀"}<small>${row ? row.level : ""}</small></div>${i + 1}</div>`;
    }
    const a = DB.abilities[s] || {name: s};
    return `<div class="sk" data-tip="${esc(a.name)}">${a.img ? `<img loading="lazy" src="${a.img}" alt="">` : ""}${i + 1}</div>`;
  }).join("");

  const talents = [...d.talents].reverse().map(t => {
    const [R, L] = t.options; // в игре первый талант уровня — справа
    const opt = o => !o ? "<div></div>" : `<div class="topt ${t.sample && o.pick >= .5 ? "pick" : ""}">
      <span class="pc">${t.sample ? pct(o.pick) : "–"}</span>${esc(talentName(o.name))}
      <div class="bar" style="width:${o.pick * 100}%"></div></div>`;
    return `<div class="trow">${opt(L)}<div class="lv">${t.level}</div>${opt(R)}</div>`;
  }).join("");

  const nm = key => esc((DB.items[key] || {}).name || key);
  const icon = key => (DB.items[key] || {}).img ? `<img loading="lazy" src="${DB.items[key].img}" alt="">` : "";
  const bar = x => `<div class="pbar"><i style="width:${Math.round(x * 100)}%"></i></div>`;
  const start = d.start.map(s => `<div class="ic" data-tip="${nm(s.key)} — берут в ${pct(s.share)} игр">
      <div class="pic">${icon(s.key)}${s.count > 1 ? `<span class="cnt">×${s.count}</span>` : ""}</div>
      <div class="nm">${nm(s.key)}</div>${bar(s.share)}<div class="sub">${pct(s.share)} игр</div></div>`).join("");
  const core = d.core.map((c, i) => `<div class="ic core" data-tip="${nm(c.key)}: обычно покупают на ${mmss(c.time)}, берут в ${pct(c.share)} игр, винрейт с ним ${pct(c.wr)}">
      <div class="pic">${icon(c.key)}<span class="step">${i + 1}</span></div>
      <div class="nm">${nm(c.key)}</div><div class="when">~${Math.round(c.time / 60)} мин</div>${bar(c.share)}<div class="sub">${pct(c.share)} игр</div></div>`).join("");
  const sit = d.situational.map(c => `<div class="ic" data-tip="${nm(c.key)}: ~${mmss(c.time)}, берут в ${pct(c.share)} игр, винрейт ${pct(c.wr)} (${c.n} игр)">
      <div class="pic">${icon(c.key)}</div><div class="nm">${nm(c.key)}</div>${bar(c.share)}<div class="sub">${pct(c.share)} игр · ~${Math.round(c.time / 60)} мин</div></div>`).join("");

  const th = DB.meta.thresholds;
  const games = d.pro.map(g => {
    let badge = "";
    if (g.flag === "stomp") badge = `<span class="badge stomp" data-tip="Перевес команды до ${k(g.maxAdv)} или GPM сильно выше обычного. Билд мог быть «жадным» — повторять только при таком же ходе игры">Игра шла очень хорошо · ${k(g.maxAdv)}</span>`;
    if (g.flag === "hard") badge = `<span class="badge hard" data-tip="Команда отставала до ${k(g.minAdv)}. Билд мог быть оборонительным">Тяжёлая игра · ${k(g.minAdv)}</span>`;
    const its = g.items.map(i => itemTile(i.key, mins(i.time), "gi" + (i.odd ? " odd" : ""),
      `${(DB.items[i.key] || {}).name} — ${mmss(i.time)}, перевес команды ${k(i.adv)}${i.odd ? " · НЕ из стандартного билда" : ""}`)).join("");
    return `<div class="game"><div class="ghead">
      <span class="pl">${esc(g.player)}</span>
      <span class="res ${g.win ? "w" : "l"}">${g.win ? "Победа" : "Поражение"}</span>
      <span class="sm">${g.k}/${g.d}/${g.a} · ${g.gpm} GPM · ${mmss(g.dur)} · ${esc(g.league || "")} · ${ago(g.date)}</span>
      ${badge}
      <a href="https://www.opendota.com/matches/${g.match}" target="_blank" rel="noopener">OpenDota</a>
      <a href="https://stratz.com/matches/${g.match}" target="_blank" rel="noopener">STRATZ</a>
    </div><div class="gitems">${its}</div></div>`;
  }).join("");

  card.innerHTML = head(hero, d) + `<div class="tabs">${tabs}</div>
    ${d.games < MIN_SAMPLE ? `<div class="warn">Мало про-игр на этой позиции (${d.games}). Смотри на конкретные матчи ниже, статистика может быть случайной.</div>` : ""}
    <h2>Прокачка скиллов</h2><div class="skills">${skills}</div>
    <h2>Таланты</h2><div class="talents">${talents}</div>
    <h2>Старт</h2><div class="items">${start || '<span class="stats">—</span>'}</div>
    <h2>Основной билд — по порядку покупки</h2><div class="items">${core || '<span class="stats">—</span>'}</div>
    <h2>Ситуативные предметы — по популярности</h2><div class="items">${sit || '<span class="stats">—</span>'}</div>
    <h2>Про-игры</h2>
    <div class="legend"><i></i> — предмет не из стандартного билда · порог «игра шла очень хорошо»: ${k(th.stompAdv)} к ${th.stompMinute}-й минуте</div>
    <div class="pro">${games}</div>`;
  bind(hero);
  window.scrollTo(0, 0);
}
function head(hero, d) {
  return `<div class="head"><button class="back">← Герои</button><img src="${hero.img}" alt="">
    <div><h1>${esc(hero.name)}</h1>${d ? `<div class="stats"><b>${d.games}</b> про-игр · винрейт <b>${pct(d.wr)}</b> · GPM <b>${d.gpm ?? "?"}</b></div>` : ""}</div></div>`;
}
function bind(hero) {
  $("#card").querySelectorAll(".tab[data-pos]").forEach(b => b.onclick = () => showHero(hero.id, +b.dataset.pos));
  $("#card .back").onclick = () => { location.hash = ""; route(); $("#q").focus(); $("#q").select(); };
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
  DB = await (await fetch("data/index.json")).json();
  const m = DB.meta;
  $("#meta").innerHTML = `Патч ${esc(m.patch)} · ${m.matches} про-матчей за ${m.days} дн.<br>обновлено ${new Date(m.updated * 1000).toLocaleString("ru-RU")}`;
  $("#q").addEventListener("input", () => { if (!$("#grid").hidden) renderGrid(); else { location.hash = ""; route(); } });
  $("#q").addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const h = filterHeroes($("#q").value).find(h => Object.keys(h.positions).length) || filterHeroes($("#q").value)[0];
      if (h) showHero(h.id);
    }
  });
  $("#grid").addEventListener("click", e => {
    const el = e.target.closest(".hero");
    if (el) showHero(+el.dataset.id);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { location.hash = ""; route(); $("#q").focus(); $("#q").select(); }
    else if (e.key === "/" && document.activeElement !== $("#q")) { e.preventDefault(); $("#q").focus(); $("#q").select(); }
  });
  window.addEventListener("hashchange", route);
  route();
})();
