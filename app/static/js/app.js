"use strict";
/* 予約フローのフロント。サーバの JSON API を叩いて 4 ステップを進める。 */

const state = {
  menus: [],
  menu: null,        // 選択中メニュー
  days: [],          // 当該メニューの空き枠(日付ごと)
  weekOffset: 0,     // カレンダー表示の週オフセット
  selectedDate: null,
  selectedSlot: null, // {start, time}
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};

/* ---- ステップ切替 ---------------------------------------------------------- */
function goStep(n) {
  ["menu", "datetime", "form", "done"].forEach((name, i) => {
    $("#panel-" + name).classList.toggle("hidden", i + 1 !== n);
  });
  document.querySelectorAll("#steps li").forEach((li) => {
    const s = Number(li.dataset.step);
    li.classList.toggle("active", s === n);
    li.classList.toggle("done", s < n);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---- STEP1: メニュー ------------------------------------------------------- */
async function loadMenus() {
  const res = await fetch("/api/config");
  const data = await res.json();
  state.menus = data.menus || [];
  const list = $("#menu-list");
  list.innerHTML = "";
  if (state.menus.length === 0) {
    list.appendChild(el("p", "loading", "予約できるメニューがありません。"));
    return;
  }
  state.menus.forEach((m) => {
    const card = el("button", "menu-card");
    card.appendChild(el("span", "menu-name", m.name));
    const meta = el("span", "menu-meta");
    meta.appendChild(el("span", "menu-dur", `${m.duration_min}分`));
    if (m.price != null) meta.appendChild(el("span", "menu-price", `¥${Number(m.price).toLocaleString()}`));
    if (m.location) meta.appendChild(el("span", "menu-loc", m.location));
    card.appendChild(meta);
    if (m.description) card.appendChild(el("span", "menu-desc", m.description));
    card.addEventListener("click", () => selectMenu(m));
    list.appendChild(card);
  });
}

async function selectMenu(menu) {
  state.menu = menu;
  state.weekOffset = 0;
  state.selectedDate = null;
  state.selectedSlot = null;
  $("#chosen-menu").textContent = `選択中: ${menu.name}（${menu.duration_min}分）`;
  goStep(2);
  await loadSlots();
}

/* ---- STEP2: 日時 ----------------------------------------------------------- */
async function loadSlots() {
  const grid = $("#cal-grid");
  grid.innerHTML = "";
  grid.appendChild(el("p", "loading", "空き状況を確認中…"));
  $("#time-grid").innerHTML = "";
  $("#time-title").style.display = "none";
  try {
    const res = await fetch("/api/slots?menu_id=" + encodeURIComponent(state.menu.id));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      grid.innerHTML = "";
      grid.appendChild(el("p", "loading", err.detail || "空き状況を取得できませんでした。"));
      return;
    }
    const data = await res.json();
    state.days = data.days || [];
    renderCalendar();
  } catch (e) {
    grid.innerHTML = "";
    grid.appendChild(el("p", "loading", "通信に失敗しました。再読み込みしてください。"));
  }
}

const WEEK_PER_PAGE = 7;
function renderCalendar() {
  const grid = $("#cal-grid");
  grid.innerHTML = "";
  const start = state.weekOffset * WEEK_PER_PAGE;
  const slice = state.days.slice(start, start + WEEK_PER_PAGE);

  if (slice.length) {
    const a = slice[0].date, b = slice[slice.length - 1].date;
    $("#cal-range").textContent = `${fmtDateShort(a)} 〜 ${fmtDateShort(b)}`;
  }
  $("#cal-prev").disabled = state.weekOffset === 0;
  $("#cal-next").disabled = start + WEEK_PER_PAGE >= state.days.length;

  slice.forEach((d) => {
    const has = d.slots.length > 0;
    const cell = el("button", "cal-cell" + (has ? "" : " disabled"));
    cell.appendChild(el("span", "cal-wd", d.weekday));
    cell.appendChild(el("span", "cal-day", String(Number(d.date.slice(8, 10)))));
    cell.appendChild(el("span", "cal-mark", has ? `${d.slots.length}枠` : "×"));
    if (has) {
      cell.addEventListener("click", () => selectDate(d, cell));
    } else {
      cell.disabled = true;
    }
    if (state.selectedDate === d.date) cell.classList.add("selected");
    grid.appendChild(cell);
  });
}

function selectDate(day, cell) {
  state.selectedDate = day.date;
  state.selectedSlot = null;
  document.querySelectorAll(".cal-cell").forEach((c) => c.classList.remove("selected"));
  cell.classList.add("selected");

  const tg = $("#time-grid");
  tg.innerHTML = "";
  $("#time-title").style.display = "";
  day.slots.forEach((s) => {
    const b = el("button", "time-cell", s.time);
    b.addEventListener("click", () => {
      state.selectedSlot = s;
      document.querySelectorAll(".time-cell").forEach((c) => c.classList.remove("selected"));
      b.classList.add("selected");
      openForm(day, s);
    });
    tg.appendChild(b);
  });
}

/* ---- STEP3: フォーム ------------------------------------------------------- */
function openForm(day, slot) {
  $("#chosen-slot").innerHTML =
    `<strong>${state.menu.name}</strong>（${state.menu.duration_min}分）<br>` +
    `${fmtDateLong(day.date)}（${day.weekday}） ${slot.time}〜`;
  $("#form-error").textContent = "";
  goStep(3);
}

async function submitBooking(e) {
  e.preventDefault();
  const form = $("#booking-form");
  const btn = $("#submit-btn");
  const errBox = $("#form-error");
  errBox.textContent = "";

  const payload = {
    menu_id: state.menu.id,
    start: state.selectedSlot.start,
    name: form.name.value.trim(),
    email: form.email.value.trim(),
    phone: form.phone.value.trim(),
    note: form.note.value.trim(),
  };
  if (!payload.name) { errBox.textContent = "お名前を入力してください。"; return; }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email)) {
    errBox.textContent = "メールアドレスを正しく入力してください."; return;
  }

  btn.disabled = true;
  btn.textContent = "予約しています…";
  try {
    const res = await fetch("/api/bookings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      errBox.textContent = data.detail || "予約に失敗しました。時間を選び直してください。";
      btn.disabled = false;
      btn.textContent = "この内容で予約する";
      return;
    }
    showDone(data);
  } catch (e2) {
    errBox.textContent = "通信に失敗しました。もう一度お試しください。";
    btn.disabled = false;
    btn.textContent = "この内容で予約する";
  }
}

/* ---- STEP4: 完了 ----------------------------------------------------------- */
function showDone(data) {
  $("#done-detail").innerHTML =
    `<div class="done-row"><span>メニュー</span><b>${data.menu_name}（${data.duration_min}分）</b></div>` +
    `<div class="done-row"><span>日時</span><b>${data.display}〜</b></div>` +
    (data.location ? `<div class="done-row"><span>場所</span><b>${data.location}</b></div>` : "");
  $("#done-note").textContent =
    data.warning || "ご入力のメールアドレスに確認の招待をお送りしました。ご確認ください。";
  const btn = $("#submit-btn");
  btn.disabled = false;
  btn.textContent = "この内容で予約する";
  goStep(4);
}

/* ---- 日付フォーマット ------------------------------------------------------ */
function fmtDateShort(iso) {
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)}`;
}
function fmtDateLong(iso) {
  const [y, m, d] = iso.split("-");
  return `${y}年${Number(m)}月${Number(d)}日`;
}

/* ---- 初期化 ---------------------------------------------------------------- */
function init() {
  loadMenus();
  document.querySelectorAll(".back").forEach((b) =>
    b.addEventListener("click", () => goStep(b.dataset.back === "menu" ? 1 : 2))
  );
  $("#cal-prev").addEventListener("click", () => { state.weekOffset--; renderCalendar(); });
  $("#cal-next").addEventListener("click", () => { state.weekOffset++; renderCalendar(); });
  $("#booking-form").addEventListener("submit", submitBooking);
  $("#again-btn").addEventListener("click", () => {
    state.menu = null; state.selectedDate = null; state.selectedSlot = null;
    goStep(1);
  });
}
document.addEventListener("DOMContentLoaded", init);
