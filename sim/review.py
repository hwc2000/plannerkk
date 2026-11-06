"""The run's report page: what a first-time reader needs first, then the review queue, then the detail.

The page is a fragment (no <html>/<head>): it is published as an Artifact, which
adds the document skeleton.  Review marks and notes live in the page's store
(collection ``reviews``, one document per run and item) so Claude can read them;
without the store they stay in the viewer's browser and can be copied out.
"""
import html
import json
import re

from .metrics import UNDO_DAYS, ideal_length
from .personas import BY_ID, SLOTS, at_week

DEPTH_WORDS = re.compile(r"\d+\s*장|챕터|기출|모의고사|교재|\d+\s*회차|단원")
TEST_LABELS = {"length": "길이", "time_of_day": "시간대", "daily_load": "하루량", "completion": "완료", "progress": "진척",
               "extraction": "읽기"}
PART = {"morning": "오전", "evening": "저녁", "afternoon": "오후", None: "모름", "unknown": "모름", "variable": "그때그때"}
REASON = {"time_shortage": "시간 부족", "task_too_large": "작업이 큼", "fatigue": "피로", "interruption": "방해",
          "priority_changed": "우선순위", "unclear_task": "불명확", "underestimated": "과소 추정", "other": "기타", None: "—"}

CSS = """
/* Layout: one reading column; the summary matrix and tables scroll inside their own frames. */
:root {
  --paper: #f5f6f8; --sheet: #ffffff; --ink: #18202b; --muted: #5b6676; --rule: #dde1e7;
  --accent: #2f55c8; --accent-soft: #e6ecfb;
  --pass: #1d7a4a; --pass-bg: #e3f3ea; --fail: #b4322a; --fail-bg: #fbe7e5; --na: #7b8492; --na-bg: #eceef1;
  --warn: #9a5b00; --warn-bg: #fdf0d9;
  --f-body: "IBM Plex Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper: #11151b; --sheet: #181d25; --ink: #e6e9ee; --muted: #9aa4b2; --rule: #2a313c;
  --accent: #8aa6ff; --accent-soft: #1f2a45;
  --pass: #6fd39d; --pass-bg: #163325; --fail: #ff8f86; --fail-bg: #3a1d1b; --na: #9aa4b2; --na-bg: #232a34;
  --warn: #f0b75a; --warn-bg: #362a14; color-scheme: dark; } }
:root[data-theme="dark"] {
  --paper: #11151b; --sheet: #181d25; --ink: #e6e9ee; --muted: #9aa4b2; --rule: #2a313c;
  --accent: #8aa6ff; --accent-soft: #1f2a45;
  --pass: #6fd39d; --pass-bg: #163325; --fail: #ff8f86; --fail-bg: #3a1d1b; --na: #9aa4b2; --na-bg: #232a34;
  --warn: #f0b75a; --warn-bg: #362a14; color-scheme: dark; }
body { background: var(--paper); color: var(--ink); font-family: var(--f-body); font-size: 15px; line-height: 1.6; }
.wrap { max-width: 1080px; margin: 0 auto; padding-block: 28px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 28px; }
h1, h2, h3 { text-wrap: balance; line-height: 1.3; margin: 0; }
h1 { font-size: 1.7rem; font-weight: 700; }
h2 { font-size: 1.2rem; font-weight: 700; }
h3 { font-size: 1rem; font-weight: 600; }
p { margin: 0; max-width: 68ch; }
.eyebrow { font-family: var(--f-mono); font-size: .75rem; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.muted { color: var(--muted); }
.num { font-family: var(--f-mono); font-variant-numeric: tabular-nums; }
section { display: grid; gap: 12px; min-width: 0; }
.sheet { background: var(--sheet); border: 1px solid var(--rule); border-radius: 10px; padding: 16px; min-width: 0; }
.facts { display: flex; flex-wrap: wrap; gap: 8px 20px; color: var(--muted); font-size: .9rem; }
.facts b { color: var(--ink); font-weight: 600; }
.scroll { overflow-x: auto; min-width: 0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--rule); }
th { font-weight: 600; color: var(--muted); font-size: .8rem; white-space: nowrap; }
td.who { min-width: 180px; }
td.who small { display: block; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { display: inline-flex; gap: 4px; align-items: baseline; padding: 1px 7px; border-radius: 999px; font-size: .78rem; white-space: nowrap; }
.chip.pass { background: var(--pass-bg); color: var(--pass); }
.chip.fail { background: var(--fail-bg); color: var(--fail); }
.chip.na { background: var(--na-bg); color: var(--na); }
.chip.warn { background: var(--warn-bg); color: var(--warn); }
.chip .num { font-size: .75rem; }
.belief { font-size: .85rem; }
.belief .arrow { color: var(--muted); }
.queue { display: grid; gap: 10px; }
.group { display: grid; gap: 6px; }
.item { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; padding: 10px 12px;
  border: 1px solid var(--rule); border-radius: 8px; background: var(--sheet); }
.item.flagged { border-color: var(--fail); }
.item.done { opacity: .6; }
.item .marks { display: flex; gap: 6px; }
.item button { font: inherit; font-size: .78rem; padding: 2px 8px; border-radius: 6px; border: 1px solid var(--rule);
  background: var(--paper); color: var(--ink); cursor: pointer; }
.item button[aria-pressed="true"].ok { background: var(--pass-bg); color: var(--pass); border-color: var(--pass); }
.item button[aria-pressed="true"].bad { background: var(--fail-bg); color: var(--fail); border-color: var(--fail); }
.item .body { min-width: 0; display: grid; gap: 2px; }
.item .body small { color: var(--muted); }
.help { font-size: .85rem; }
.note { display: grid; gap: 4px; font-size: .82rem; color: var(--muted); margin-top: 6px; }
.note textarea { font: inherit; font-size: .88rem; color: var(--ink); background: var(--paper); border: 1px solid var(--fail);
  border-radius: 6px; padding: 6px 8px; resize: vertical; width: 100%; box-sizing: border-box; }
table.grid { font-size: .82rem; margin-top: 8px; width: auto; min-width: 100%; }
table.grid th, table.grid td { padding: 5px 8px; white-space: nowrap; }
table.grid tbody th, table.grid tfoot th { color: var(--ink); font-size: .82rem; }
table.grid tfoot td, table.grid tfoot th { border-bottom: 0; color: var(--muted); }
.t { display: inline-block; margin: 1px 4px 1px 0; padding: 1px 6px; border-radius: 5px; font-family: var(--f-mono); font-size: .76rem; }
.t b { font-weight: 600; }
.t.done { background: var(--pass-bg); color: var(--pass); }
.t.part { background: var(--warn-bg); color: var(--warn); }
.t.miss { background: var(--fail-bg); color: var(--fail); }
.t.plan { background: var(--na-bg); color: var(--na); }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.bar button { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid var(--accent); background: var(--accent-soft);
  color: var(--accent); cursor: pointer; }
textarea#copy-out { width: 100%; min-height: 120px; font-family: var(--f-mono); font-size: .8rem; background: var(--sheet);
  color: var(--ink); border: 1px solid var(--rule); border-radius: 8px; padding: 8px; box-sizing: border-box; }
details.person { background: var(--sheet); border: 1px solid var(--rule); border-radius: 10px; }
details.person > summary { cursor: pointer; padding: 14px 16px; display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; }
details.person > div { padding: 0 16px 16px; display: grid; gap: 16px; min-width: 0; }
.week { display: grid; gap: 8px; border-top: 1px solid var(--rule); padding-top: 12px; min-width: 0; }
.mins { font-family: var(--f-mono); font-size: .8rem; color: var(--muted); word-break: break-word; }
.say { background: var(--paper); border-radius: 8px; padding: 8px 10px; font-size: .88rem; }
.got { font-size: .82rem; }
.miss { color: var(--fail); font-weight: 600; }
ul.plain { margin: 0; padding-left: 18px; display: grid; gap: 2px; }
@media (max-width: 560px) { body { font-size: 14px; } .item { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

JS = """
(function () {
  const run = document.body.dataset.run;
  const legacyKey = 'sim-review-' + document.body.dataset.started;
  const localKey = 'sim-review2-' + run;
  const items = Array.from(document.querySelectorAll('.item'));
  const byId = {};
  items.forEach(function (item) { byId[item.dataset.id] = item; });
  function readLocal(key) { try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (e) { return {}; } }
  const legacy = readLocal(legacyKey), saved = readLocal(localKey), state = {};
  items.forEach(function (item) {
    const id = item.dataset.id, old = legacy[item.dataset.legacy];
    state[id] = saved[id] || { mark: old || null, note: '' };
  });
  function saveLocal() { try { localStorage.setItem(localKey, JSON.stringify(state)); } catch (e) {} }
  const storeNote = document.getElementById('store-note');
  const writing = {}, pending = {}, timers = {};
  let db = null, readOnly = false;

  function paint(item) {
    const s = state[item.dataset.id] || {};
    item.classList.toggle('flagged', s.mark === 'bad');
    item.classList.toggle('done', s.mark === 'ok');
    item.querySelector('.ok').setAttribute('aria-pressed', String(s.mark === 'ok'));
    item.querySelector('.bad').setAttribute('aria-pressed', String(s.mark === 'bad'));
    const label = item.querySelector('.note'), box = label.querySelector('textarea');
    label.hidden = s.mark !== 'bad';
    if (document.activeElement !== box && box.value !== (s.note || '')) box.value = s.note || '';
  }
  function count() {
    const seen = items.filter(function (i) { return state[i.dataset.id].mark; }).length;
    const bad = items.filter(function (i) { return state[i.dataset.id].mark === 'bad'; }).length;
    document.getElementById('progress').textContent = seen + ' / ' + items.length + '개 확인 · 이상함 ' + bad + '개';
  }
  function showPast(list) {
    const box = document.getElementById('past'), out = document.getElementById('past-list');
    out.textContent = '';
    list.sort(function (a, b) { return String(a.run).localeCompare(String(b.run)); }).forEach(function (body) {
      const p = document.createElement('p'), head = document.createElement('b');
      head.textContent = '[' + body.run + '] ' + (body.text || '');
      p.appendChild(head);
      p.appendChild(document.createElement('br'));
      p.appendChild(document.createTextNode('메모: ' + body.note));
      out.appendChild(p);
    });
    box.hidden = list.length === 0;
  }
  function docRef(id) { return db.collection('reviews').doc(run + '--' + id); }
  async function write(id) {
    saveLocal();
    if (!db || readOnly) return;
    if (writing[id]) { pending[id] = true; return; }
    writing[id] = true;
    try {
      const s = state[id];
      if (!s.mark && !s.note) await docRef(id).delete();
      else await docRef(id).set({ run: run, item: id, text: byId[id].dataset.text, mark: s.mark || null,
                                  note: s.note || '', updatedAt: new Date().toISOString() });
    } catch (e) {
      if (e && e.code === 'invalid_argument') {
        readOnly = true;
        storeNote.textContent = '이 화면에서는 공유 저장이 안 돼요. 표시는 이 브라우저에만 남아요.';
      } else {
        storeNote.textContent = '저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.';
      }
    } finally {
      writing[id] = false;
      if (pending[id]) { pending[id] = false; write(id); }
    }
  }
  items.forEach(function (item) {
    const id = item.dataset.id, box = item.querySelector('textarea');
    paint(item);
    item.querySelectorAll('.marks button').forEach(function (button) {
      button.addEventListener('click', function () {
        const value = button.classList.contains('ok') ? 'ok' : 'bad';
        state[id].mark = state[id].mark === value ? null : value;
        paint(item); count(); write(id);
        if (state[id].mark === 'bad') box.focus();
      });
    });
    box.addEventListener('input', function () {
      state[id].note = box.value;
      clearTimeout(timers[id]);
      timers[id] = setTimeout(function () { timers[id] = null; write(id); }, 800);
    });
  });
  count();

  const found = window.claude && window.claude.use ? window.claude.use('db') : Promise.resolve(null);
  found.then(function (store) {
    if (!store) { storeNote.textContent = '표시는 이 브라우저에만 남아요. 다 보면 복사해서 대화창에 붙여 주세요.'; return; }
    db = store;
    let first = true;
    const slow = setTimeout(function () { storeNote.textContent = '저장소에 아직 연결 중이에요. 표시는 이 브라우저에도 남아요.'; }, 10000);
    db.collection('reviews').onSnapshot(function (snap) {
      const past = [];
      snap.docs.forEach(function (doc) {
        const body = doc.data() || {}, id = body.item;
        if (body.run !== run) {
          if (body.mark === 'bad' && body.note) past.push(body);
          return;
        }
        if (!byId[id] || writing[id] || timers[id]) return;
        state[id] = { mark: body.mark || null, note: body.note || '' };
      });
      showPast(past);
      items.forEach(paint); count(); saveLocal();
      if (snap.metadata.fromCache) return;
      clearTimeout(slow);
      storeNote.textContent = '표시와 메모는 공유 저장소에 저장돼요. Claude가 바로 읽을 수 있어요.';
      if (!first) return;
      first = false;
      const stored = {};
      snap.docs.forEach(function (doc) { const b = doc.data() || {}; if (b.run === run) stored[b.item] = true; });
      // Marks made while they lived only in this browser move to the store once.
      (async function () {
        for (const item of items) {
          const s = state[item.dataset.id];
          if (!stored[item.dataset.id] && (s.mark || s.note)) await write(item.dataset.id);
        }
      })();
    }, function () {
      clearTimeout(slow);
      db = null;
      storeNote.textContent = '공유 저장소에 연결하지 못했어요. 표시는 이 브라우저에만 남아요.';
    });
  });

  document.getElementById('copy').addEventListener('click', function () {
    const lines = [];
    items.forEach(function (item) {
      const s = state[item.dataset.id];
      if (s.mark) lines.push((s.mark === 'bad' ? '[이상함] ' : '[괜찮음] ') + item.dataset.text + (s.note ? ' — 메모: ' + s.note : ''));
    });
    const text = lines.length ? lines.join('\\n') : '(표시한 항목이 없어요)';
    const out = document.getElementById('copy-out');
    out.hidden = false; out.value = text;
    const note = document.getElementById('copy-note');
    const fallback = function () { out.select(); note.textContent = '아래 글을 직접 복사해 주세요.'; };
    try { navigator.clipboard.writeText(text).then(function () { note.textContent = '복사했어요.'; }, fallback); } catch (e) { fallback(); }
  });
})();
"""


CSS += """
.lead { display: grid; gap: 10px; }
.lead ol { margin: 0; padding-left: 20px; display: grid; gap: 4px; max-width: 72ch; }
dl.terms { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0; font-size: .88rem; }
dl.terms dt { font-weight: 600; }
dl.terms dd { margin: 0; color: var(--muted); }
@media (max-width: 560px) { dl.terms { grid-template-columns: 1fr; } dl.terms dd { margin-bottom: 6px; } }
.chip.right { background: var(--pass-bg); color: var(--pass); }
.chip.under { background: var(--warn-bg); color: var(--warn); }
.chip.wrong { background: var(--fail-bg); color: var(--fail); }
.chip.nofield { background: var(--na-bg); color: var(--na); }
td.verdict { min-width: 220px; }
.past { display: grid; gap: 6px; }
.past p { font-size: .86rem; }
.t.skip { background: var(--na-bg); color: var(--na); font-family: var(--f-body); }
"""

TRAITS = [("block", "작업 길이"), ("offBlock", "안 맞는 때 길이"), ("focusTime", "잘 되는 시간대"),
          ("daily", "하루 분량"), ("pace", "걸리는 배율")]
STATE_WORDS = {"right": "맞음", "under": "덜 앎", "wrong": "틀림", "nofield": "칸 없음"}


def esc(value):
    return html.escape(str(value), quote=True)


def chip(kind, label, value=None):
    inner = esc(label) + (f' <span class="num">{esc(value)}</span>' if value is not None else "")
    return f'<span class="chip {kind}">{inner}</span>'


def truth_line(p):
    bits = [f"집중 {p.focus}분"]
    if p.best:
        bits.append(f"{PART[p.best]}형 (다른 때 ×{p.off_focus})")
    if p.pace != 1:
        bits.append(f"계획의 {p.pace}배 걸림")
    if p.capacity:
        bits.append(f"하루 {p.capacity}분이면 지침")
    if p.skip:
        bits.append(f"체크인 {p.skip:.0%} 빼먹음")
    if p.phrasing == "casual":
        bits.append("짧고 애매하게 말함")
    for start, values in p.changes:
        bits.append(f"{start}주차부터 " + ", ".join(f"하루 {v}분이면 지침" if k == "capacity" else k for k, v in values.items() if k != "remarks"))
    return " · ".join(bits)


def shown(app, key):
    if key == "pace":
        return f"{app}%" if app else "모름(100%)"
    if app is None:
        return "없음" if key == "daily" else "모름"
    if key == "focusTime":
        return PART.get(app, app)
    return f"{app}분" if isinstance(app, int) else str(app)


def truth_shown(truth, key):
    if key == "focusTime":
        return "상관없음" if truth is None else PART.get(truth, truth)
    if key == "daily":
        return f"{truth}분" if truth else "제한 없음"
    if key == "pace":
        return f"{truth}%"
    return f"{truth}분"


def relevant(p, key, last):
    """Traits worth showing for this person: the ones their truth has, plus any the app got wrong."""
    cell = last.get(key)
    if cell is None:
        return False
    return {"block": True, "offBlock": bool(p.best), "focusTime": bool(p.best) or cell["state"] == "wrong",
            "daily": bool(p.capacity) or any(c for s, c in p.changes if "capacity" in c) or cell["state"] == "wrong",
            "pace": p.pace != 1}[key]


def verdict_line(p, metrics, person):
    """One plain sentence on how this user went, from the same rules for everyone."""
    last = person["beliefs"][-1] if person["beliefs"] else {}
    wrong_changes = sum(1 for m in metrics for x in m.get("proposals", []) if x.get("verdict") == "wrong")
    keys = [k for k, _ in TRAITS if relevant(p, k, last)]
    labels = dict(TRAITS)
    wrong = [labels[k] for k in keys if last[k]["state"] == "wrong"]
    missing = [labels[k] for k in keys if last[k]["state"] in ("under", "nofield")]
    done = (metrics[-1].get("tests") or {}).get("completion", {}).get("pass") if metrics else False
    parts = []
    if not wrong and not missing:
        parts.append("다 배웠고 계획도 맞아요." if done else "필요한 건 다 배웠는데 계획이 따라가지 않아요.")
    else:
        if wrong:
            parts.append(f"잘못 알고 있어요: {', '.join(wrong)}.")
        if missing:
            parts.append(f"아직 못 배웠어요: {', '.join(missing)}.")
    if wrong_changes:
        parts.append(f"근거 없이 바꾼 적 {wrong_changes}번.")
    stuck = sum(1 for m in metrics for x in m.get("proposals", [])
                if x.get("verdict") != "wrong" and x.get("worseAfterProbe")
                and (x.get("undoneAfter") is None or x["undoneAfter"] > UNDO_DAYS))
    if stuck:
        parts.append(f"늘려 본 뒤 나빠졌는데 안 되돌린 적 {stuck}번.")
        wrong_changes += stuck
    kind = "pass" if not wrong and not missing and done and not wrong_changes else "fail" if wrong or wrong_changes else "warn"
    return kind, " ".join(parts)


def learned_text(person, p):
    out = []
    names = {"block": "작업 길이", "focusTime": "시간대"}
    for key, day in person["learned"].items():
        if key == "focusTime" and not p.best:
            continue
        out.append(f"{names[key]} " + ("처음부터" if day == 0 else f"{day}일째" if day else "못 맞힘"))
    return " · ".join(out)


def verdict_table(summary):
    rows = []
    for pid, metrics in summary["metrics"].items():
        p, person = BY_ID[pid], summary["people"][pid]
        kind, line = verdict_line(p, metrics, person)
        last = metrics[-1] if metrics else {}
        done = (last.get("tests") or {}).get("completion", {}).get("value")
        tag = ' <span class="chip na">검증용</span>' if p.holdout else ""
        rows.append(f'<tr><td class="who"><b>{esc(p.label)}</b>{tag}<small>{esc(truth_line(p))}</small></td>'
                    f'<td class="verdict">{chip(kind, {"pass": "좋음", "warn": "부족", "fail": "문제"}[kind])} {esc(line)}</td>'
                    f'<td class="num">{"—" if done is None else f"{done:.0%}"}</td><td>{esc(learned_text(person, p))}</td></tr>')
    return (f'<div class="sheet scroll"><table><thead><tr><th>가상 사용자</th><th>한 줄 결론</th><th>마지막 주 완료율</th>'
            f'<th>앱이 맞힌 날</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def storage_table(summary):
    rows = []
    for pid, person in summary["people"].items():
        a, p = person["audit"], BY_ID[pid]
        ok = a["missing"] == 0 and a["duplicated"] == 0 and a["sessions"] == a["reportedDays"] and a["feedback"] == a["plannedWeeks"]
        reading = a["reading"]
        right = sum(1 for v in reading.values() if v["right"])
        empty = sum(1 for v in reading.values() if v["right"] is None)
        rows.append(f'<tr><td class="who"><b>{esc(p.label)}</b></td>'
                    f'<td>{chip("pass" if ok else "fail", "빠짐없음" if ok else "문제")}</td>'
                    f'<td class="num">{a["toldTasks"]} → {a["records"]}<small class="muted"> (빠짐 {a["missing"]} · 중복 {a["duplicated"]})</small></td>'
                    f'<td class="num">{a["sessions"]} / {a["reportedDays"]}</td><td class="num">{a["feedback"]} / {a["plannedWeeks"]}</td>'
                    f'<td class="num">{a["overrunsStored"]}</td>'
                    f'<td>{chip("pass" if right == len(reading) else "warn", "맞음", f"{right}/{len(reading)}")}'
                    f'{" " + chip("na", "빈 칸", empty) if empty else ""}</td></tr>')
    return (f'<div class="sheet scroll"><table><thead><tr><th>가상 사용자</th><th>저장</th><th>체크인한 작업 → 기록</th>'
            f'<th>체크인한 날 → 저장</th><th>주간 의견</th><th>계획보다 오래 걸린 기록</th><th>알게 된 것 읽기</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def belief_table(summary):
    rows = []
    for pid, person in summary["people"].items():
        p = BY_ID[pid]
        last = person["beliefs"][-1] if person["beliefs"] else {}
        cells = []
        for key, label in TRAITS:
            if not relevant(p, key, last):
                cells.append('<td class="muted">—</td>')
                continue
            weeks = "".join(chip(b[key]["state"], f"{b['week']}주") for b in person["beliefs"] if b.get(key))
            c = last[key]
            cells.append(f'<td><div class="chips">{chip(c["state"], STATE_WORDS[c["state"]])}</div>'
                         f'<small class="muted">앱 {esc(shown(c["app"], key))} / 진짜 {esc(truth_shown(c["truth"], key))}</small>'
                         f'<div class="chips">{weeks}</div></td>')
        rows.append(f'<tr><td class="who"><b>{esc(p.label)}</b></td>{"".join(cells)}</tr>')
    head = "".join(f"<th>{label}</th>" for _, label in TRAITS)
    return (f'<div class="sheet scroll"><table><thead><tr><th>가상 사용자</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def week_cell(m):
    if not m.get("tests"):
        return '<td><span class="chip na">계획 없음</span></td>'
    chips = []
    for key in ("length", "time_of_day", "daily_load", "completion", "progress"):
        test = m["tests"].get(key)
        if not test:
            continue
        value = test["value"]
        text = f"{value:.0%}" if key != "daily_load" else f"{value}분"
        chips.append(chip("pass" if test["pass"] else "fail", TEST_LABELS[key], text))
    changes = [x for x in m.get("proposals", []) if x.get("approved")]
    if changes:
        wrong = [x for x in changes if x.get("verdict") == "wrong"]
        chips.append(chip("fail" if wrong else "warn", "변경", f"{len(changes)}" + (f" (잘못 {len(wrong)})" if wrong else "")))
    if m.get("skippedDays"):
        chips.append(chip("na", "체크인 안 한 날", m["skippedDays"]))
    return f'<td><div class="chips">{"".join(chips)}</div></td>'


def summary_table(summary):
    weeks = summary["run"]["weeks"]
    head = "".join(f"<th>{w}주차</th>" for w in range(1, weeks + 1))
    rows = []
    for pid, metrics in summary["metrics"].items():
        p = BY_ID[pid]
        cells = "".join(week_cell(m) for m in metrics) + "<td></td>" * (weeks - len(metrics))
        rows.append(f'<tr><td class="who"><b>{esc(p.label)}</b><small>기대: {esc(p.expect)}</small></td>{cells}</tr>')
    for pid, error in summary["errors"].items():
        rows.append(f'<tr><td class="who"><b>{esc(BY_ID[pid].label)}</b></td><td colspan="{weeks}">'
                    f'<span class="chip fail">실행 실패</span> <span class="mins">{esc(error[-300:])}</span></td></tr>')
    return (f'<div class="sheet scroll"><table><thead><tr><th>가상 사용자</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def divergence_table(summary):
    weeks = summary["run"]["weeks"]
    head = "".join(f"<th>{w}주차</th>" for w in range(1, weeks + 1))
    rows = []
    for pid, cells in summary["divergence"].items():
        if pid == "steady":
            continue
        tds = []
        for cell in cells:
            if not cell:
                tds.append("<td>—</td>")
                continue
            tds.append(f'<td class="num">작업 {cell["avgTask"]:+g}분<br>오전 {cell["morningShare"]:+.0%}<br>하루 {cell["dailyPlanned"]:+d}분</td>')
        rows.append(f'<tr><td class="who"><b>{esc(BY_ID[pid].label)}</b></td>{"".join(tds)}</tr>')
    return (f'<div class="sheet scroll"><table><thead><tr><th>대조군과의 차이</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


RULE_NAMES = {"long-task-v2": "줄이기 규칙", "focus-grow-v1": "늘리기 규칙", "focus-time-v1": "시간대 규칙"}
FIELD_NAMES = {"blockMinutes": "작업 상한", "focusTime": "잘 되는 시간대", "dailyPlannedMinutes": "하루 계획량"}
MISS_FIELDS = {"actualMinutes": "실제로 한 분", "reasonCode": "못 한 이유", "focus": "집중", "condition": "컨디션"}
SLOT_NAMES = {"tone": "말투", "place": "주로 하는 곳", "atmosphere": "잘 맞는 분위기", "focus_aids": "집중 습관",
              "distractions": "집중 깨는 이유", "task_order": "일하는 순서", "condition": "컨디션에 영향", "rest": "쉬는 방식"}
RESULT_CLASS = {"completed": "done", "partial": "part", "not_started": "miss", None: "plan"}
RESULT_WORD = {"completed": "완료", "partial": "일부", "not_started": "못 함", None: "계획"}
GROUP_HELP = {
    "늘려 본 뒤 나빠졌는데 되돌리지 않음": "직전엔 잘 끝내서 늘려 본 것까진 괜찮지만, 늘린 뒤 완료율이 떨어졌는데 일주일 안에 원래대로 돌리지 않았어요.",
    "승인할 수 없는 변경 카드 (앱 버그)": "프로필이 바뀐 뒤 남은 예전 제안이에요. 화면에 계속 뜨는데 승인하면 항상 거절돼요.",
    "근거 없이 바꾼 변경": "사람마다 최대 3개만 보여요. 앱이 승인받아 바꾼 값인데, 그때 앱이 가진 기록으로는 바꿀 근거가 없었어요. 규칙을 고쳐야 하면 이상함, 괜찮다고 보면 넘기세요.",
    "사람 판단: 이 한 주가 이 사람에게 맞나": "마지막 주예요. 시간표에서 작업 길이, 오전·저녁, 하루 합계를 보고 판단해 주세요. 초록 완료, 노랑 일부, 빨강 못 함, 회색 체크인 안 함.",
    "체크인 말을 AI가 다르게 읽음": "사람마다 최대 2개만 보여요. 그 사람이 쓴 문장과 AI가 기록한 값이 달라요. 말하지 않은 숫자를 채웠으면 ‘지어냄’이에요.",
    "알게 된 것이 엉뚱하게 저장됨": "체크인에서 그 사람에 대해 알게 된 값이 다른 칸에 들어갔거나 답과 달라요.",
    "작업 깊이 규칙 위반 의심": "사용자가 말하지 않은 교재 장·기출을 지어낸 작업이에요.",
    "자유 발언이 계획 AI까지 안 감": "칸에 안 맞는 말이 다음 계획을 만들 때 AI에게 전달되지 않았어요.",
    "계획 생성 실패·재시도": "계획 만들기가 실패했어요. 금요일 밤에 변경을 승인하면 이번 주에 남은 시간이 없어 재계획이 실패해요. 앱 화면에서도 오류로 보여요.",
    "체크인 실패": "체크인 저장이 실패했어요.",
}


def undo_words(x):
    days = x.get("undoneAfter")
    return "그 뒤로 원래 값으로 돌아간 적 없음" if days is None else f"{days}일 뒤 원래 값으로 돌아감"


def change_words(changes):
    parts = []
    for key, change in changes.items():
        before, after = change.get("from"), change.get("to")
        if key == "focusTime":
            before, after = PART.get(before, before), PART.get(after, after)
        elif isinstance(before, int) or isinstance(after, int):
            before = f"{before}분" if before is not None else "없음"
            after = f"{after}분" if after is not None else "없음"
        parts.append(f"{FIELD_NAMES.get(key, key)} {before} → {after}")
    return ", ".join(parts)


def look_for(p, week):
    """What a person can check on a week's timetable, from the user's truth that week (same formula for all)."""
    p = at_week(p, week)
    hints = [f"작업 길이가 {ideal_length(p):.0f}분 이하인가"]
    if p.best:
        off = "저녁" if p.best == "morning" else "오전"
        hints.append(f"{off} 작업이 {min(p.focus * p.off_focus, 120) / p.pace:.0f}분 이하인가")
    if p.capacity:
        hints.append(f"하루 합계가 {p.capacity}분 근처인가")
    if p.pace > 1:
        hints.append(f"작업 사이에 여유가 있나 (계획의 {p.pace}배 걸림)")
    return " · ".join(hints)


def week_grid(week):
    """The week as a timetable: weekday rows, morning and evening columns, the day's total."""
    from datetime import date, timedelta
    outs = [o for d in week["days"] for o in d["outcomes"]]
    skipped = {d["date"] for d in week["days"] if d.get("skipped")}
    told = bool(outs)
    if not outs:
        plan = next((x for x in week["plans"] if x["tasks"]), None)
        outs = [{"title": t["title"], "start": t["start"], "planned": t["minutes"], "result": None, "actual": 0}
                for t in (plan or {}).get("tasks", [])]
    monday = date.fromisoformat(week["monday"])
    names = "월화수목금"
    rows, totals = [], {"morning": 0, "evening": 0}
    for offset in range(5):
        day = (monday + timedelta(days=offset)).isoformat()
        cells = {"morning": [], "evening": []}
        planned = done = 0
        for o in sorted((o for o in outs if o["start"][:10] == day), key=lambda o: o["start"]):
            part = "morning" if int(o["start"][11:13]) < 15 else "evening"
            totals[part] += o["planned"]
            planned += o["planned"]
            done += o["planned"] if o["result"] == "completed" else 0
            cells[part].append(f'<span class="t {RESULT_CLASS[o["result"]]}" title="{esc(o["title"])} · {RESULT_WORD[o["result"]]}">'
                               f'{o["start"][11:16]} <b>{o["planned"]}분</b></span>')
        total = (f'<span class="num">{planned}분</span>' + (f' <small class="muted">끝냄 {done}</small>' if told else "")
                 + (' <span class="t skip">체크인 안 함</span>' if day in skipped else "")) if planned else '<span class="muted">0분</span>'
        rows.append(f'<tr><th>{names[offset]} {day[5:]}</th><td>{"".join(cells["morning"]) or "<span class=muted>—</span>"}</td>'
                    f'<td>{"".join(cells["evening"]) or "<span class=muted>—</span>"}</td><td>{total}</td></tr>')
    whole = totals["morning"] + totals["evening"]
    share = f"{totals['morning'] / whole:.0%}" if whole else "—"
    return (f'<div class="scroll"><table class="grid"><thead><tr><th></th><th>오전 10–12시</th><th>저녁 19–21시</th><th>하루 합계</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody><tfoot><tr><th>주간</th><td class="num">{totals["morning"]}분</td>'
            f'<td class="num">{totals["evening"]}분</td><td class="num">오전 비율 {share}</td></tr></tfoot></table></div>')


def queue_items(results, summary):
    """What a person has to look at: things code cannot judge, or code flagged.

    Each item: (key, text, detail, extra html).  ``key`` names the item the same way
    on every rebuild, so review marks stored by it survive a rebuild of the page.
    """
    groups = {}

    def add(group, key, text, detail="", extra=""):
        groups.setdefault(group, []).append((key, text, detail, extra))

    caps = {"근거 없이 바꾼 변경": 3, "체크인 말을 AI가 다르게 읽음": 2}
    for pid, result in results.items():
        p = BY_ID[pid]
        counted = {}

        def add(group, key, text, detail="", extra=""):  # noqa: F811 - per user, a few of each kind is enough to judge
            counted[group] = counted.get(group, 0) + 1
            if counted[group] <= caps.get(group, 99):
                groups.setdefault(group, []).append((key, text, detail, extra))
        for m in summary["metrics"][pid]:
            for n, x in enumerate(m.get("proposals", [])):
                change = f"{p.label} · {m['week']}주차 · {RULE_NAMES.get(x['rule'], x['rule'])}: {change_words(x['changes'])}"
                if x.get("verdict") == "wrong":
                    add("근거 없이 바꾼 변경", f"{pid}-w{m['week']}-change{n}", change,
                        f"앱이 댄 근거: {x.get('reason') or '—'} {x.get('sizing') or ''} · 왜 문제: {x.get('why')} · "
                        f"{undo_words(x)} · 이 사람의 진짜: {truth_line(p)}")
                elif x.get("worseAfterProbe") and (x.get("undoneAfter") is None or x["undoneAfter"] > UNDO_DAYS):
                    add("늘려 본 뒤 나빠졌는데 되돌리지 않음", f"{pid}-w{m['week']}-probe{n}", change,
                        f"완료율 {x['recentCompletion']:.0%} → 바꾼 뒤 일주일 {x['completionAfter']:.0%} · {undo_words(x)}")
            for miss in (m.get("tests", {}).get("extraction") or {}).get("misses", []):
                invented = miss["truth"] is None
                add("체크인 말을 AI가 다르게 읽음", f"{pid}-{miss['date']}-{miss['task']}-{miss['field']}",
                    f"{p.label} · {miss['date']} · {MISS_FIELDS.get(miss['field'], miss['field'])}"
                    + (" · 지어냄" if invented else ""),
                    f"쓴 말: “{miss.get('words', '')}” → 정답 {miss['truth'] if not invented else '(말 안 함)'}, "
                    f"AI가 기록 {miss['got'] if miss['got'] is not None else '(못 읽음)'}")
        for card in summary["people"][pid].get("staleCards", []):
            add("승인할 수 없는 변경 카드 (앱 버그)", f"{pid}-stale-{card['first']}",
                f"{p.label} · {RULE_NAMES.get(card['rule'], card['rule'])}: {change_words(card['changes'])}",
                f"{card['first'][5:10]}부터 {card['last'][5:10]}까지 {card['tries']}번 승인을 눌렀지만 매번 거절: "
                f"{card['error'].split(': ', 1)[-1]}")
        for key, v in summary["people"][pid]["audit"]["reading"].items():
            # Only fields with a fixed right answer: free-text fields are worded freshly every time.
            if v["right"] is False and key in p.told:
                add("알게 된 것이 엉뚱하게 저장됨", f"{pid}-insight-{key}",
                    f"{p.label} · {SLOT_NAMES.get(key, key)}: “{v['got']}”", f"이 사람이 이 칸에 한 답: {v['truth']}")
        for week in result["weeks"]:
            for plan in week["plans"]:
                for t in plan["tasks"]:
                    if DEPTH_WORDS.search(t["title"] or "") or DEPTH_WORDS.search(t.get("doneWhen") or ""):
                        add("작업 깊이 규칙 위반 의심", f"{pid}-w{week['week']}-{t['id']}",
                            f"{p.label} · {week['week']}주차 · {t['title']}", t.get("doneWhen") or "")
                if plan.get("failed") or plan.get("errors"):
                    counted["plan-fail"] = counted.get("plan-fail", 0) + 1
            for day in week["days"]:
                if day.get("error"):
                    add("체크인 실패", f"{pid}-{day['date']}-checkin", f"{p.label} · {day['date']}", day["error"][:300])
        if counted.get("plan-fail"):
            add("계획 생성 실패·재시도", f"{pid}-plan-fail", f"{p.label} · 계획 만들기 실패 {counted['plan-fail']}번",
                "대부분 금요일 밤에 변경을 승인해서 이번 주에 남은 시간이 없어 재계획이 실패한 경우예요.")
        for row in summary["remarks"].get(pid, {}).get("rows", []):
            if row["reachedPlanAI"] is False:
                add("자유 발언이 계획 AI까지 안 감", f"{pid}-{row['date']}-remark", f"{p.label} · {row['date']} · “{row['remark']}”")
        weeks = result["weeks"]
        if weeks:
            for week in weeks[-1:]:
                if any(x["tasks"] for x in week["plans"]):
                    add("사람 판단: 이 한 주가 이 사람에게 맞나", f"{pid}-w{week['week']}-week",
                        f"{p.label} · {week['week']}주차", f"볼 것: {look_for(p, week['week'])}", week_grid(week))
    order = ["근거 없이 바꾼 변경", "늘려 본 뒤 나빠졌는데 되돌리지 않음", "승인할 수 없는 변경 카드 (앱 버그)",
             "사람 판단: 이 한 주가 이 사람에게 맞나", "체크인 말을 AI가 다르게 읽음",
             "알게 된 것이 엉뚱하게 저장됨", "자유 발언이 계획 AI까지 안 감", "작업 깊이 규칙 위반 의심",
             "계획 생성 실패·재시도", "체크인 실패"]
    return [(g, groups[g]) for g in order if g in groups]


def item_id(key):
    """A short id for a review item that stays the same across rebuilds (FNV-1a of its key)."""
    h = 0x811C9DC5
    for byte in key.encode("utf-8"):
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"i{h:08x}"


def queue_html(results, summary):
    parts, n = [], 0
    for group, items in queue_items(results, summary):
        rows = []
        for key, text, detail, extra in items:
            n += 1
            iid = item_id(key)
            rows.append(f'<div class="item" data-id="{iid}" data-legacy="q{n}" data-text="{esc(group + " | " + text)}">'
                        f'<div class="marks"><button type="button" class="ok" aria-pressed="false">괜찮음</button>'
                        f'<button type="button" class="bad" aria-pressed="false">이상함</button></div>'
                        f'<div class="body"><span>{esc(text)}</span>{f"<small>{esc(detail)}</small>" if detail else ""}{extra}'
                        f'<label class="note" for="note-{iid}" hidden>무엇이 이상한지 한 줄로'
                        f'<textarea id="note-{iid}" rows="2" placeholder="예: 하루 합계가 그대로 230분이라 이 사람한테 너무 많음"></textarea></label>'
                        f'</div></div>')
        parts.append(f'<div class="group"><h3>{esc(group)} <span class="muted num">{len(items)}</span></h3>'
                     f'<p class="muted help">{esc(GROUP_HELP.get(group, ""))}</p>{"".join(rows)}</div>')
    if not parts:
        parts.append('<p class="muted">검수할 항목이 없어요.</p>')
    return "".join(parts)


def change_item(x):
    when = esc(x.get("at", "")[5:16].replace("T", " "))
    why = f" — {esc(x['why'])}" if x.get("why") else ""
    failed = "" if x.get("approved") else " <span class=miss>승인 실패</span>"
    mark = " " + chip("fail", "근거 없음") if x.get("verdict") == "wrong" else \
        " " + chip("warn", "나빠짐 · " + undo_words(x)) if x.get("worseAfterProbe") else ""
    return f"<li>{when} {esc(RULE_NAMES.get(x['rule'], x['rule']))}: {esc(change_words(x['changes']))}{why}{mark}{failed}</li>"


def person_html(pid, result, metrics):
    p = BY_ID[pid]
    weeks = []
    for week, m in zip(result["weeks"], metrics):
        plans = "".join(f'<li>{esc(x["label"])} · 작업 {len(x["tasks"])}개'
                        f'{" · <span class=miss>실패</span>" if x.get("failed") else ""}</li>' for x in week["plans"])
        props = "".join(change_item(x) for x in m.get("proposals", [])) or "<li class='muted'>없음</li>"
        days = []
        for day in [d for d in week["days"] if not d.get("skipped")][:2]:
            days.append(f'<div class="say"><b>{esc(day["date"])}</b> {esc(day.get("text", ""))}</div>')
        weeks.append(f'<div class="week"><h3>{week["week"]}주차 <span class="muted">({esc(week["monday"])}~)</span></h3>'
                     f'<p class="muted">완료 {m.get("completion", 0):.0%} · 평균 작업 {m.get("avgTask", "—")}분 · 하루 계획 {m.get("dailyPlanned", "—")}분 · '
                     f'못 한 이유 {esc(", ".join(f"{REASON.get(k, k)} {v}" for k, v in (m.get("reasons") or {}).items()) or "없음")}</p>'
                     f'{week_grid(week)}'
                     f'<div><b>계획</b><ul class="plain">{plans}</ul></div><div><b>변경</b><ul class="plain">{props}</ul></div>'
                     f'<div><b>체크인 예시</b>{"".join(days)}</div></div>')
    return (f'<details class="person"><summary><h3>{esc(p.label)}</h3><span class="muted">{esc(truth_line(p))}</span></summary>'
            f'<div>{"".join(weeks)}</div></details>')


TESTS_TABLE = [
    ("길이", "작업 하나가 그 시간대에 이 사람이 버틸 수 있는 길이인가", "작업의 80% 이상이 그때 집중 시간 안 (짧은 건 괜찮음)",
     "길면 중간에 끊겨요. 오전형은 저녁 집중이 짧아서 저녁 작업도 짧아야 해요.", "작업 상한"),
    ("시간대", "잘 되는 때에 일이 몰리는가", "잘 되는 때의 계획 분이 60% 이상", "같은 시간이라도 잘 되는 때에 하면 더 끝내요.", "잘 되는 시간대"),
    ("하루량", "하루에 할 수 있는 만큼만 넣는가", "하루 계획이 처리량의 115% 이하", "지치는 사람에게 꽉 채우면 뒤 작업을 다 못 해요.", "하루 계획량"),
    ("완료", "계획한 걸 실제로 끝내는가", "작업 80% 이상 완료", "결과 지표예요. 위 값이 맞으면 올라가요.", "위 값 전부"),
    ("진척", "계획을 비워서 완료율만 올린 건 아닌가", "끝낸 분이 할 수 있는 양의 70% 이상", "작업 2개만 넣고 100% 완료는 좋은 계획이 아니에요.", "위 값 전부"),
    ("변경 근거", "앱이 값을 바꿀 때 그만한 기록이 있었나", "근거 없는 변경 0건",
     "늘려 보기는 직전 작업을 80% 이상 끝냈을 때만, 줄이기는 진짜 길이의 75% 아래로는 안 됨, 시간대는 진짜 원인일 때만. "
     "하루 분량·비워 둘 시간·시간대별 길이는 그 뒤 일주일 동안 끝낸 일이 줄었는지로 판단해요.", "변경 제안"),
    ("되돌리기", "바꾼 뒤 나빠지면 원래대로 돌렸나", "나빠진 변경을 7일 안에 되돌림",
     "늘려 보는 탐색은 실패하면 바로 돌아와야 괜찮은 거예요.", "변경 제안"),
    ("읽기", "체크인 말에서 분·이유·상태를 맞게 읽었나", "90% 이상 일치, 지어낸 값 0", "말하지 않은 숫자를 채우면 잘못 배워요.", "실행 기록"),
    ("저장", "체크인한 게 빠짐없이 한 번씩 저장됐나", "빠짐 0, 중복 0", "쌓이는 정보가 새면 배울 수 없어요.", "실행 기록·체크인"),
    ("믿는 값", "앱이 지금 믿는 값이 진짜와 맞나", "맞음 / 덜 앎(안전) / 틀림 / 칸 없음", "‘누적으로 잘 배웠나’를 직접 보여줘요.", "프로필·프로젝트 설정"),
]
TERMS = [
    ("가상 사용자", "앱을 쓰는 척하는 프로그램이에요. 진짜 성향(집중 시간 등)을 숨기고, 그대로 행동하고 체크인해요."),
    ("진짜", "가상 사용자의 숨은 성향이에요. 앱은 이걸 직접 못 보고 체크인 말과 버튼으로만 알아내야 해요."),
    ("대조군", "설문에 사실대로 답한 사람이에요. 앱이 아무것도 안 바꿔야 정상이에요."),
    ("검증용", "규칙을 고칠 때 보지 않고 남겨 둔 사람이에요. 시험 문제를 미리 안 보는 것과 같아요."),
    ("작업 상한", "앱이 정하는 작업 하나의 최대 길이예요. 체크인이 쌓이면 늘리거나 줄여요."),
    ("덜 앎", "앱이 아직 진짜를 모르지만 더 짧게·적게 잡고 있어서 계획이 망가지진 않는 상태예요."),
    ("칸 없음", "앱에 그 성향을 저장할 곳 자체가 없어요. 아무리 체크인해도 못 배워요."),
]


COMPARE_METRICS = [
    ("progress", "진척 (3·4주차)", "끝낸 계획 분 ÷ 그 사람이 할 수 있는 양", True, "pct"),
    ("completion", "완료율 (3·4주차)", "계획한 작업 중 끝낸 비율", True, "pct"),
    ("beliefs", "맞게 믿는 값", "그 사람에게 필요한 값 중 앱이 맞게 아는 비율", True, "pct"),
    ("badChanges", "근거 없는 변경", "근거 없이 바꾸거나, 나빠졌는데 안 되돌린 횟수 (사람당)", False, "num"),
    ("repeats", "이미 끝낸 작업 반복", "새 주 계획 중 지난주에 끝낸 제목을 다시 넣은 비율", False, "pct"),
    ("reading", "체크인 읽기", "AI가 쓴 체크인 글을 앱이 맞게 읽은 비율", True, "pct"),
]


def _fmt(value, kind):
    if value is None:
        return "—"
    return f"{value:.0%}" if kind == "pct" else f"{value:.1f}"


def comparison_html(compare):
    """Before/after on the same users and seeds: the seeds never looked at first, then the ones used while fixing."""
    if not compare:
        return ""
    if "sets" in compare:
        intro = ('<section class="sheet lead"><h2>앱 수정 전과 후</h2><p>같은 사람, 같은 날, 같은 씨앗으로 수정 전 앱(main)과 수정 후 앱을 '
                 '각각 돌렸어요. 체크인 글은 매번 다른 AI(gpt-4.1)가 새로 쓰고, 앱은 gpt-6.1-terra로 읽어요. '
                 '<b>검증 씨앗</b>은 규칙을 고친 뒤 처음 돌려서 결과를 보고 고친 적이 없는 것이고, <b>개발 씨앗</b>은 고치는 동안 들여다본 것이에요. '
                 '믿을 만한 건 검증 씨앗 쪽이에요.</p></section>')
        return intro + "".join(_comparison_set(item["title"], item["data"]) for item in compare["sets"])
    return _comparison_set("앱 수정 전과 후", compare)


def _comparison_set(title, compare):
    head = "".join(f"<th>{esc(label)}</th>" for _, label, _, _, _ in COMPARE_METRICS)
    rows = []
    names = {"fixed": "고정 사용자 10명 (매 씨앗 같은 성향)", "fresh": "새 사용자 (씨앗마다 새로 뽑은 성향)"}
    for group, values in compare["groups"].items():
        cells = []
        for key, _, _, higher, kind in COMPARE_METRICS:
            b, a = values[key]["before"], values[key]["after"]
            better = None if b is None or a is None or abs(a - b) < (0.02 if kind == "pct" else 0.1) else (a > b) == higher
            kind_chip = "na" if better is None else "pass" if better else "fail"
            cells.append(f'<td>{chip(kind_chip, _fmt(b, kind) + " → " + _fmt(a, kind))}</td>')
        rows.append(f'<tr><td class="who"><b>{esc(names[group])}</b><small>{values["count"]}명 · 진척이 나아진 사람 {values["better"]}명, '
                    f'나빠진 사람 {values["worse"]}명</small></td>{"".join(cells)}</tr>')
    people = []
    for r in sorted(compare["table"], key=lambda r: (r["fresh"], r["label"])):
        cells = []
        for key, _, _, higher, kind in COMPARE_METRICS:
            b, a = r[f"before.{key}"], r[f"after.{key}"]
            better = None if b is None or a is None or abs(a - b) < (0.05 if kind == "pct" else 0.5) else (a > b) == higher
            cells.append(f'<td class="num">{_fmt(b, kind)} → <b class="{"" if better is None else "" if better else "miss"}">{_fmt(a, kind)}</b></td>')
        people.append(f'<tr><td class="who">{esc(r["label"])}<small>{r["runs"]}번 실행 평균</small></td>{"".join(cells)}</tr>')
    defs = "".join(f"<li><b>{esc(label)}</b>: {esc(text)}</li>" for _, label, text, _, _ in COMPARE_METRICS)
    return (f'<section><h2>{esc(title)}</h2>'
            f'<p class="muted">씨앗 {len(compare["pairs"])}개, 씨앗마다 고정 사용자 10명과 새로 뽑은 사용자 10명.</p>'
            f'<div class="sheet scroll"><table><thead><tr><th>묶음</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            f'<ul class="plain muted">{defs}</ul>'
            f'<details class="person"><summary><h3>사람별 전후</h3><span class="muted">빨간 숫자는 나빠진 것</span></summary>'
            f'<div><div class="scroll"><table><thead><tr><th>가상 사용자</th>{head}</tr></thead><tbody>{"".join(people)}</tbody></table></div></div></details>'
            f'</section>')


def item_note(change):
    return f'<small class="muted"><br>{esc(change["item"])}</small>' if change.get("item") else ""


def presentation_html(summary, compare):
    """The part to show in a talk: what was tested, how it was judged, what changed, and what a person reviewed."""
    from pathlib import Path
    log_path = Path(__file__).with_name("review_log.json")
    log = json.loads(log_path.read_text()) if log_path.exists() else {"rounds": [], "changes": []}
    cases = []
    for pid in [p for p in summary["metrics"] if not p.startswith("fresh")]:
        p = BY_ID[pid]
        looks = ["작업 길이", "완료", "진척"]
        if p.best:
            looks.insert(1, "시간대·시간대별 길이")
        if p.capacity or any("capacity" in c for _, c in p.changes):
            looks.insert(1, "하루 분량")
        if p.pace != 1:
            looks.insert(1, "걸리는 배율")
        if p.skip:
            looks.append("저장 누락")
        if p.phrasing == "casual":
            looks.append("말 읽기·지어내기")
        if p.changes:
            looks.append("바뀐 뒤 따라가기")
        cases.append(f'<tr><td class="who"><b>{esc(p.label)}</b>{" <span class=\"chip na\">검증용</span>" if p.holdout else ""}</td>'
                     f'<td>{esc(truth_line(p))}</td><td>{esc(" · ".join(looks))}</td><td>{esc(p.expect)}</td></tr>')
    fresh = sum(1 for pid in summary["metrics"] if pid.startswith("fresh"))
    cases.append(f'<tr><td class="who"><b>새 사용자 {fresh}명</b><small>씨앗마다 새로 뽑음</small></td>'
                 f'<td>집중 25~110분, 시간대형 여부, 1~1.5배, 하루 90~180분, 체크인 0~40% 빼먹음, 말투 5가지 중 무작위</td>'
                 f'<td>위 지표 전부 (사람마다 해당하는 것)</td><td>같은 공식으로 계산 (사람별 정답 없음)</td></tr>')
    rounds = log.get("rounds") or []
    reviewed = sum(r["reviewed"] for r in rounds)
    bad = sum(r["bad"] for r in rounds)
    changes = "".join(f'<tr><td>{esc(c["round"])}</td><td>“{esc(c["quote"])}”{item_note(c)}</td>'
                      f'<td>{esc(c["change"])}</td><td>{chip("na" if c["version"] == "남은 일" else "pass", c["version"])}</td></tr>'
                      for c in log.get("changes") or [])
    result = ""
    if compare and compare.get("sets"):
        first = compare["sets"][0]
        g = first["data"]["groups"]
        rows = []
        for key, label, _, higher, kind in COMPARE_METRICS:
            cells = "".join(f'<td class="num">{_fmt(g[name][key]["before"], kind)} → <b>{_fmt(g[name][key]["after"], kind)}</b></td>'
                            for name in ("fixed", "fresh"))
            rows.append(f"<tr><td>{esc(label)}</td>{cells}</tr>")
        result = (f'<h3>결과: {esc(first["title"])}</h3><div class="scroll"><table><thead><tr><th>지표</th>'
                  f'<th>고정 사용자 {g["fixed"]["count"]}명</th><th>새 사용자 {g["fresh"]["count"]}명</th></tr></thead>'
                  f'<tbody>{"".join(rows)}</tbody></table></div>'
                  f'<p class="muted">진척이 나아진 사람: 고정 {g["fixed"]["better"]}명·새 {g["fresh"]["better"]}명, '
                  f'나빠진 사람: 고정 {g["fixed"]["worse"]}명·새 {g["fresh"]["worse"]}명.</p>')
    tests = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td><td>{e}</td></tr>" for a, b, c, d, e in TESTS_TABLE)
    return (f'<section class="sheet lead" id="talk"><span class="eyebrow">발표용 요약</span>'
            f'<h2>누적된 체크인이 계획에 반영되는지, 테스트 케이스와 사람 검수로 확인</h2>'
            f'<ol><li>가상 사용자가 같은 설문·같은 목표로 시작해 4주 동안 매일 체크인해요. 체크인 글은 다른 AI가 매번 새로 쓰고, 숫자·이유가 사실과 맞는지 코드가 확인해요.</li>'
            f'<li>앱은 체크인을 저장하고(누적), 규칙이 그 기록에서 값을 배워 제안하고, 승인하면 다음 계획에 반영해요.</li>'
            f'<li>수정 전 앱과 수정 후 앱을 같은 사람·같은 날로 돌려서 지표로 비교해요. 고칠 때 본 적 없는 씨앗으로 따로 검증해요.</li>'
            f'<li>코드가 판단 못 하는 건 사람이 검수 큐에서 판단하고 메모를 남겨요. 그 메모로 규칙을 고쳐서 다시 돌려요.</li></ol>'
            f'<h3>테스트 케이스</h3><div class="scroll"><table><thead><tr><th>가상 사용자</th><th>숨은 진짜 성향</th><th>보는 지표</th><th>좋은 계획이라면</th></tr></thead>'
            f'<tbody>{"".join(cases)}</tbody></table></div>'
            f'<h3>지표</h3><div class="scroll"><table><thead><tr><th>지표</th><th>질문</th><th>통과 기준</th><th>쓰는 누적 정보</th></tr></thead>'
            f'<tbody>{tests}</tbody></table></div>'
            f'{result}'
            f'<h3>사람 검수 → 규칙 수정</h3><p>검수 {reviewed}건(이상함 {bad}건), 메모를 남긴 항목으로 규칙을 고쳤어요.</p>'
            f'<div class="scroll"><table><thead><tr><th>회차</th><th>검수 메모 (원문)</th><th>바꾼 규칙</th><th>버전</th></tr></thead>'
            f'<tbody>{changes}</tbody></table></div></section>')


def render(results, summary, compare=None):
    run = summary["run"]
    llm_calls = sum(s["calls"] for stats in summary["llm"].values() for s in stats.values())
    llm_failed = sum(s["failed"] for stats in summary["llm"].values() for s in stats.values())
    slots = sorted({s["hour"] for s in SLOTS})
    tests = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td><td class='muted'>{d}</td><td>{e}</td></tr>"
                    for a, b, c, d, e in TESTS_TABLE)
    terms = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in TERMS)
    persons = "".join(person_html(pid, results[pid], summary["metrics"][pid]) for pid in results)
    return f"""<title>체크인 누적 실험</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap" id="top">
<header style="display:grid;gap:10px">
  <span class="eyebrow">Re:plan · 체크인 실험 {esc(run.get("name", ""))} · {esc(run.get("started", "")[:16].replace("T", " "))}</span>
  <h1>체크인이 쌓이면 계획이 그 사람에게 맞춰지나</h1>
  <p class="muted">가상 사용자 {len(run["personas"])}명이 같은 설문, 같은 프로젝트(정보처리기사 실기 준비), 같은 시간(평일 {slots[0]}–{slots[1] + 1}시·{slots[2]}–{slots[3] + 1}시)으로 시작해서
  {run["weeks"]}주 동안 매일 저녁 체크인했어요. 다른 건 숨은 ‘진짜 성향’뿐이고, 앱은 체크인 말과 버튼으로만 그걸 알 수 있어요.</p>
  <div class="facts"><span>모델 <b>{esc(run["model"])}</b></span><span>AI 호출 <b class="num">{llm_calls}</b>회</span>
  <span>실패 <b class="num">{llm_failed}</b>회</span><span>변경 제안은 가상 사용자가 모두 승인 → 앱처럼 남은 주를 재계획</span></div>
</header>
{presentation_html(summary, compare)}
{comparison_html(compare)}
<section class="sheet lead"><h2>이 페이지 읽는 법</h2>
<ol><li><b>결론</b>에서 사람마다 잘 됐는지 한 줄로 봐요.</li>
<li><b>앱이 쌓은 정보</b>에서 체크인이 빠짐없이 저장됐는지, 앱이 지금 믿는 값이 진짜와 맞는지 봐요.</li>
<li><b>검수 큐</b>에서 코드가 판단 못 하는 것을 사람이 판단해요. 나머지 표는 근거 자료예요.</li></ol>
<dl class="terms">{terms}</dl></section>
<section><h2>결론</h2>
<p class="muted">마지막 주 기준이에요. 같은 규칙으로 모두를 판단해요.</p>
{verdict_table(summary)}</section>
<section><h2>앱이 쌓은 정보</h2>
<h3>체크인이 빠짐없이 저장됐나</h3>
<p class="muted">가상 사용자가 체크인한 것과 앱 저장소에 실제로 남은 것을 맞춰 봤어요.</p>
{storage_table(summary)}
<h3>앱이 지금 믿는 값과 진짜</h3>
<p class="muted">초록 맞음, 주황 덜 앎(안전), 빨강 틀림, 회색 칸 없음. 아래 작은 칩은 주차별 변화예요.</p>
{belief_table(summary)}</section>
<section><h2>주차별 테스트</h2>
<p class="muted">칸마다 그 주의 테스트 결과예요. 초록 통과, 빨강 실패. ‘변경’은 그 주에 승인한 변경 수예요.</p>
{summary_table(summary)}</section>
<section><h2>같은 설문인데 계획이 갈라졌나</h2>
<p class="muted">대조군과 비교한 차이예요. 1주차에 0에 가깝고 뒤로 갈수록 벌어지면 체크인이 계획을 바꾼 거예요.</p>
{divergence_table(summary)}</section>
<section><h2>검수 큐</h2>
<p class="muted">괜찮으면 넘기고, 이상하면 ‘이상함’을 누른 뒤 한 줄 적어 주세요. 표시와 메모는 저장되고 Claude가 바로 읽을 수 있어요.</p>
<div class="bar"><span id="progress" class="muted num"></span><span id="store-note" class="muted">저장 위치 확인 중…</span><button type="button" id="copy">표시한 항목 복사</button><span id="copy-note" class="muted"></span></div>
<textarea id="copy-out" hidden readonly></textarea>
<div class="sheet past" id="past" hidden><h3>이전 실행에서 남긴 메모</h3><div id="past-list"></div></div>
<div class="queue">{queue_html(results, summary)}</div></section>
<section><h2>사용자별 상세</h2>{persons}</section>
<section><h2>테스트 정의</h2>
<p class="muted">목표값은 모든 사용자에게 같은 공식으로, 각자의 진짜 성향에서 계산해요. 사람별로 정해 둔 정답은 없어요.</p>
<div class="sheet scroll"><table><thead><tr><th>테스트</th><th>질문</th><th>통과 기준</th><th>왜 필요한가</th><th>연결된 앱 값</th></tr></thead><tbody>{tests}</tbody></table></div></section>
</div>
<script>document.body.dataset.run = {json.dumps(run.get("name", "run"))}; document.body.dataset.started = {json.dumps(run.get("started", "run"))};{JS}</script>
"""
