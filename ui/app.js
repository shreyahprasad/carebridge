// CareBridge case page. Reads the synthetic cases and renders a case list plus
// the selected case: its details (#/case/<id>) or its provider matches
// (#/case/<id>/providers). Data is rendered as text only (never as HTML).
const DATA_URL = '../data/cases.json';
// Latest saved run per case, written by the match and trip workflows (see ui/README.md).
const runUrl = (kind, id) => `../data/runs/${kind}/${encodeURIComponent(id)}-latest.json`;
const RUN_VERSION = { match: 'match-result-v1', trip: 'trip-plan-v1' };

const CARE_MODE = {
  in_person: 'In person only',
  in_person_preferred: 'In person preferred',
  telehealth: 'Telehealth',
  telehealth_preferred: 'Telehealth preferred',
  either: 'In person or telehealth',
  any: 'In person or telehealth',
};
const ENGLISH = { none: 'No English', basic: 'Basic English', intermediate: 'Some English', fluent: 'Fluent English' };

// Tiers in caseworker words (match/models.py Tier).
const TIER = {
  A: { label: 'Strong match', hint: 'Speaks her language, in DC, coverage fits' },
  B: { label: 'Possible match', hint: 'Speaks her language; outside DC or cost to confirm' },
  C: { label: 'Interpreter needed', hint: 'In DC and coverage fits, but needs an interpreter' },
};
// Reachability grades, best first (trip/models.py Grade).
const GRADE = {
  walk: { label: 'Walkable', kind: 'good' },
  one_bus: { label: 'One bus', kind: 'good' },
  drive: { label: 'Drive', kind: 'ok' },
  hard: { label: 'Hard trip', kind: 'attn' },
  unknown: { label: 'Location unknown', kind: 'muted' },
  not_realistic: { label: 'Not realistic', kind: 'bad' },
};
const MODE = {
  live: 'AI-assisted run',
  scripted: 'Scripted test run',
  rules_only: 'Rules only, no AI',
};

let cases = [];
// Per case: { match, trip } where each is a result, null (no run yet) or an Error.
const runs = new Map();
let sortBy = null; // 'reach' | 'fit'; null = default for the data present
let renderToken = 0;

// Small element builder: h('div', {class: 'x'}, 'text', child)
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

const fullName = c => [c.first_name, c.last_name].filter(Boolean).join(' ');
const initials = c => [(c.first_name || '')[0], (c.last_name || '')[0]].filter(Boolean).join('').toUpperCase() || '?';
const yesNo = v => (v === true ? 'Yes' : v === false ? 'No' : null);
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : s);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const telHref = p => `tel:${String(p).split(/\s*x/i)[0].replace(/[^\d+]/g, '')}`;
// Only http(s) links from the data become clickable.
const safeUrl = u => (/^https?:\/\//i.test(u || '') ? u : null);

function insuranceLabel(c) {
  const ins = c.insurance || {};
  if (!ins.type) return null;
  if (ins.type === 'uninsured') return 'Uninsured';
  return ins.plan ? `${ins.type} · ${ins.plan}` : ins.type;
}

function languageLabel(c) {
  return (c.languages || []).join(', ') || null;
}

function urgencyPill(c) {
  const u = c.urgency || 'routine';
  return h('span', { class: `pill urg-${u}` }, cap(u));
}

// Short flags for the list card and the "needs from care" row.
// kind: 'key' = provider-matching input, 'attn' = barrier to plan around.
function needs(c) {
  const out = [];
  const lang = languageLabel(c);
  if (lang) out.push({ kind: 'key', text: lang + (c.english_level ? ` · ${ENGLISH[c.english_level] || c.english_level}` : '') });
  if (c.care_mode_needed) out.push({ kind: 'key', text: CARE_MODE[c.care_mode_needed] || c.care_mode_needed });
  const ins = insuranceLabel(c);
  if (ins) out.push({ kind: c.insurance.type === 'uninsured' ? 'attn' : 'key', text: ins });
  const pref = c.preferences || {};
  if (pref.provider_gender && pref.provider_gender !== 'no preference') out.push({ kind: 'key', text: `Prefers a ${pref.provider_gender} provider` });
  if (pref.trauma_informed) out.push({ kind: 'key', text: 'Trauma-informed' });
  if (c.pregnant) out.push({ kind: 'attn', text: `Pregnant${c.pregnancy_weeks ? ` · ${c.pregnancy_weeks} wks` : ''}` });
  if (typeof c.age === 'number' && c.age < 18) out.push({ kind: 'attn', text: 'Minor' });
  if (c.guardian && /not (her|his|their)? ?legal guardian/i.test(c.guardian)) out.push({ kind: 'attn', text: 'No legal guardian present' });
  if (c.has_car === false) out.push({ kind: 'attn', text: 'No car' });
  if (c.childcare_during_appointments === 'needed') out.push({ kind: 'attn', text: 'Needs childcare' });
  if (c.has_phone === false) out.push({ kind: 'attn', text: 'No phone' });
  const noDataPhone = c.has_phone === false || /no data|basic/i.test(c.phone_type || '');
  if (c.has_computer === false && noDataPhone) out.push({ kind: 'attn', text: 'No internet device' });
  return out;
}

const chip = n => h('span', { class: `chip chip-${n.kind}` }, n.text);

function buildList() {
  const list = document.getElementById('cases');
  list.replaceChildren(...cases.map(c => {
    const flags = needs(c);
    return h('li', {},
      h('button', {
        class: 'case-item',
        type: 'button',
        'data-id': c.id,
        onclick: () => { location.hash = `#/case/${encodeURIComponent(c.id)}`; },
      },
        h('div', { class: 'case-top' },
          h('span', { class: 'avatar', 'aria-hidden': 'true' }, initials(c)),
          h('div', {},
            h('div', { class: 'case-name' }, fullName(c)),
            h('div', { class: 'case-sub' }, [c.age && `${c.age}`, languageLabel(c)].filter(Boolean).join(' · ')),
          ),
          urgencyPill(c),
        ),
        c.mental_health_concerns && h('p', { class: 'case-concern' }, c.mental_health_concerns),
        h('div', { class: 'chips' }, flags.slice(0, 3).map(chip),
          flags.length > 3 && h('span', { class: 'chip' }, `+${flags.length - 3} more`)),
      ),
    );
  }));
  document.getElementById('case-count').textContent = plural(cases.length, 'case', 'cases');
}

function markSelected(selectedId) {
  for (const btn of document.querySelectorAll('.case-item')) {
    btn.setAttribute('aria-current', btn.dataset.id === selectedId ? 'true' : 'false');
  }
}

// A fact row is skipped when its value is missing, so new or partial cases still render.
function facts(rows) {
  const items = rows.filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!items.length) return null;
  return h('dl', { class: 'facts' }, items.map(([k, v]) => h('div', { class: 'fact' }, h('dt', {}, k), h('dd', {}, v))));
}

function card(title, rows) {
  const body = facts(rows);
  return body && h('section', { class: 'card' }, h('h3', {}, title), body);
}

const caseHref = (c, tab) => `#/case/${encodeURIComponent(c.id)}${tab === 'providers' ? '/providers' : ''}`;

function tabs(c, tab) {
  const link = (key, text) => h('a', {
    class: 'tab', href: caseHref(c, key), 'data-tab': key, 'aria-current': tab === key ? 'page' : false,
  }, text);
  return h('nav', { class: 'tabs', 'aria-label': 'Case views' }, link('case', 'Case'), link('providers', 'Providers'));
}

// Shared header. The case view shows the full header; the providers view a compact one.
function header(c, tab) {
  const full = tab === 'case';
  return h('div', { class: `detail-head${full ? '' : ' compact'}` },
    h('div', { class: 'detail-title' },
      h('span', { class: 'avatar', 'aria-hidden': 'true' }, initials(c)),
      h('div', {},
        h('h2', { tabindex: '-1', id: 'case-title' }, fullName(c)),
        h('div', { class: 'case-sub' }, [c.age && `${c.age} years old`, c.id, c.synthetic && 'synthetic'].filter(Boolean).join(' · ')),
      ),
      urgencyPill(c),
    ),
    full && c.mental_health_concerns && h('p', { class: 'concern' }, c.mental_health_concerns),
    full && h('div', { class: 'contact' },
      c.phone && h('span', {}, `☎ ${c.phone}`),
      c.address && h('span', {}, c.address),
    ),
    h('div', { class: 'needs' },
      full && h('div', { class: 'label' }, 'Needs from care'),
      h('div', { class: 'chips' }, (full ? needs(c) : needs(c).slice(0, 4)).map(chip),
        !full && needs(c).length > 4 && h('a', { class: 'chip chip-more', href: caseHref(c, 'case') }, `+${needs(c).length - 4} more`)),
    ),
    full && h('div', { class: 'actions' },
      h('a', { class: 'btn btn-primary', href: caseHref(c, 'providers') }, 'Find providers'),
      h('span', { class: 'hint' }, 'Shows the latest provider match for this case.'),
    ),
    tabs(c, tab),
  );
}

function caseBody(c) {
  const pref = c.preferences || {};
  const hh = c.household || {};
  const kids = Array.isArray(c.children)
    ? (c.children.length ? c.children.map(k => (k && k.age != null ? `${k.age} yrs` : 'age unknown')).join(', ') : 'None')
    : null;
  const cw = c.caseworker || {};
  return [
    h('div', { class: 'sections' },
      card('Language', [
        ['Speaks', languageLabel(c)],
        ['English', c.english_level && (ENGLISH[c.english_level] || c.english_level)],
        ['Interpreter OK', yesNo(pref.interpreter_ok)],
      ]),
      card('Getting to care', [
        ['Care mode', c.care_mode_needed && (CARE_MODE[c.care_mode_needed] || c.care_mode_needed)],
        ['Why', c.care_mode_note],
        ['Phone', c.has_phone === false ? 'No phone' : c.phone_type],
        ['Computer', yesNo(c.has_computer)],
        ['Car', yesNo(c.has_car)],
        ['Gets around by', (c.transportation_options || []).join(', ') || null],
        ['Childcare', c.childcare_during_appointments && cap(c.childcare_during_appointments)],
      ]),
      card('Coverage and status', [
        ['Immigration', c.immigration_status && cap(c.immigration_status)],
        ['Insurance', insuranceLabel(c)],
        ['SNAP', yesNo(c.snap)],
        ['Household', hh.size != null ? `${hh.size} people` : null],
        ['Monthly income', typeof hh.monthly_income_usd === 'number' ? `$${hh.monthly_income_usd.toLocaleString()}` : null],
      ]),
      card('Family and school', [
        ['Pregnant', c.pregnant ? `Yes${c.pregnancy_weeks ? `, ${c.pregnancy_weeks} weeks` : ''}` : yesNo(c.pregnant)],
        ['Children', kids],
        ['Guardian', c.guardian && cap(c.guardian)],
        ['School', c.school],
      ]),
      card('Preferences', [
        ['Provider', pref.provider_gender && cap(pref.provider_gender)],
        ['Trauma-informed', yesNo(pref.trauma_informed)],
      ]),
    ),
    cw.notes && h('section', { class: 'notes' },
      h('div', { class: 'label' }, 'Caseworker notes'),
      h('p', {}, cw.notes),
      cw.name && h('div', { class: 'who' }, `— ${cw.name}`),
    ),
  ];
}

// ---------- runs ----------

async function loadRun(kind, id) {
  const res = await fetch(runUrl(kind, id), { cache: 'no-store' });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${kind} run: HTTP ${res.status}`);
  const data = await res.json();
  if (!data || data.version !== RUN_VERSION[kind]) throw new Error(`${kind} run: expected ${RUN_VERSION[kind]}, got ${data && data.version}`);
  if (data.case_id !== id) throw new Error(`${kind} run belongs to ${data.case_id}, not ${id}`);
  return data;
}

async function runsFor(id) {
  if (runs.has(id)) return runs.get(id);
  const settle = p => p.catch(err => (err instanceof Error ? err : new Error(String(err))));
  const [match, trip] = await Promise.all([settle(loadRun('match', id)), settle(loadRun('trip', id))]);
  const entry = { match, trip };
  runs.set(id, entry);
  return entry;
}

// Fields the match used that the case page can recompute; a difference means the case
// was edited after the run. Compared on the scrubbed needs profile only.
function changedSinceMatch(c, n) {
  if (!n) return [];
  const coverage = { 'DC Medicaid': 'medicaid', uninsured: 'uninsured' }[(c.insurance || {}).type] || 'other';
  const pref = c.preferences || {};
  const checks = [
    ['age', c.age, n.age],
    ['languages', (c.languages || []).join('|'), (n.languages || []).join('|')],
    ['English level', c.english_level, n.english_level],
    ['coverage', coverage, n.coverage],
    ['care mode', c.care_mode_needed, n.care_mode],
    ['pregnancy', Boolean(c.pregnant), n.pregnant],
    ['car', Boolean(c.has_car), n.has_car],
    ['childcare', c.childcare_during_appointments === 'needed', n.childcare_needed],
    ['provider preference', pref.provider_gender || 'no preference', n.provider_gender],
    ['urgency', c.urgency, n.urgency],
  ];
  return checks.filter(([, a, b]) => b !== undefined && a !== b).map(([name]) => name);
}

// ---------- call checklist (saved in this browser only) ----------

const tickKey = (caseId, providerId, q) => `carebridge.ask.${caseId}.${providerId}.${q}`;
function getTick(key) { try { return localStorage.getItem(key) === '1'; } catch { return false; } }
function setTick(key, on) { try { on ? localStorage.setItem(key, '1') : localStorage.removeItem(key); } catch { /* not saved */ } }

// items: [{ key, text, ai }]. onChange runs after a tick so a summary count can update.
function checklist(caseId, providerId, items, onChange) {
  if (!items.length) return null;
  return h('ul', { class: 'asks' }, items.map(({ key, text, ai }) => {
    const k = tickKey(caseId, providerId, key);
    const id = `ask-${providerId}-${key}`.replace(/[^\w-]/g, '_');
    return h('li', {},
      h('input', { type: 'checkbox', id, checked: getTick(k), onchange: e => { setTick(k, e.target.checked); if (onChange) onChange(); } }),
      h('label', { for: id }, text, ai && h('span', { class: 'ai-tag' }, 'AI-suggested')),
    );
  }));
}
const askedCount = (caseId, providerId, items) => items.filter(i => getTick(tickKey(caseId, providerId, i.key))).length;

function aiNote(text, title = 'AI note') {
  return text && h('div', { class: 'ai-note' },
    h('div', { class: 'label' }, `${title} · not checked`),
    h('p', {}, text),
  );
}

// Folded sections remember being open across re-renders (sort, reload of runs).
const openFolds = new Set();
function fold(key, cls, summary, ...body) {
  const el = h('details', { class: `fold ${cls}`, open: openFolds.has(key) }, h('summary', {}, summary), ...body);
  el.addEventListener('toggle', () => { el.open ? openFolds.add(key) : openFolds.delete(key); });
  return el;
}

// ---------- providers view ----------

function gradeBadge(grade) {
  const g = GRADE[grade];
  return g && h('span', { class: `grade grade-${g.kind}` }, g.label);
}

function benefitStrip(c, trip) {
  if (!trip || trip instanceof Error) {
    return h('section', { class: 'strip strip-empty' },
      h('span', { class: 'label' }, 'Ride and fare help'),
      trip instanceof Error
        ? h('span', { class: 'error-text' }, `Could not read the trip plan: ${trip.message}`)
        : h('span', {}, 'Not planned yet. Run ', h('code', {}, `python -m trip ${c.id}`), '.'),
    );
  }
  const benefits = trip.benefits || [];
  if (!benefits.length) {
    return h('section', { class: 'strip strip-empty' }, h('span', { class: 'label' }, 'Ride and fare help'), h('span', {}, 'No ride or fare program found for her.'));
  }
  return fold(`${c.id}|benefits`, 'strip',
    [h('span', { class: 'label' }, 'Ride and fare help'), h('span', { class: 'strip-names' }, benefits.map(b => b.name).join(' · '))],
    h('div', { class: 'benefits' }, benefits.map(b => h('div', { class: 'benefit' },
      h('div', { class: 'benefit-name' }, b.name, h('span', { class: `conf conf-${b.confidence}` }, `${cap(b.confidence)} confidence`)),
      b.how_to_access && h('p', {}, b.how_to_access),
      (b.notes || []).length > 0 && h('ul', { class: 'benefit-notes' }, b.notes.map(n => h('li', {}, n))),
      h('div', { class: 'benefit-meta' },
        b.phone && h('a', { href: telHref(b.phone) }, `☎ ${b.phone}`),
        (b.sources || []).map(s => safeUrl(s.url) && h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title || 'Source')),
      ),
    ))),
    h('p', { class: 'verify' }, 'Research data, not independently verified. Confirm before relying on it.'),
  );
}

function rideSummary(stop) {
  const uses = stop.benefits || [];
  if (uses.some(u => u.use === 'likely')) return 'rides or fares likely covered';
  if (uses.length) return 'ride help only if confirmed';
  return null;
}

function tripSection(c, pick, stop, benefitsById) {
  if (!stop) {
    return h('div', { class: 'trip-empty' },
      h('span', { class: 'label' }, 'Getting there'),
      h('span', {}, 'Not planned yet'),
    );
  }
  const questionText = Object.fromEntries((stop.questions || []).map(q => [q.code, q.text]));
  const uses = (stop.benefits || []).map(u => {
    const name = (benefitsById[u.program_id] || {}).name || u.program_id;
    return h('li', { class: `use use-${u.use}` },
      u.use === 'likely'
        ? [h('strong', {}, name), ': likely covered']
        : [h('strong', {}, name), `: only if ${questionText[u.question] ? `the answer is yes to "${questionText[u.question]}"` : 'confirmed'}`]);
  });
  const asks = checklist(c.id, pick.provider_id, [
    ...(stop.questions || []).map(q => ({ key: `trip.${q.code}`, text: q.text })),
    ...(stop.extra_questions || []).map((t, i) => ({ key: `trip.x${i}.${t.slice(0, 40)}`, text: t, ai: true })),
  ]);
  const time = stop.time_estimate && (/estimate/i.test(stop.time_estimate) ? stop.time_estimate : `${stop.time_estimate} (estimate)`);
  const steps = stop.steps || [];
  return fold(`${c.id}|${pick.provider_id}|trip`, 'trip',
    [h('span', { class: 'label' }, 'Getting there'), h('span', { class: 'fold-sum' }, [time, rideSummary(stop)].filter(Boolean).join(' · ') || stop.grade_basis || '')],
    stop.grade_basis && h('p', { class: 'muted' }, stop.grade_basis),
    uses.length ? h('ul', { class: 'uses' }, uses) : h('p', { class: 'muted' }, 'No ride or fare program applies to this trip.'),
    asks && h('div', { class: 'sub' }, h('div', { class: 'label' }, 'Check for this trip'), asks),
    (steps.length > 0 || stop.tell_client) && fold(`${c.id}|${pick.provider_id}|steps`, 'inner',
      h('span', {}, 'Booking steps and what to tell her', h('span', { class: 'ai-tag' }, 'AI-written, not checked')),
      steps.length > 0 && h('ol', { class: 'steps' }, steps.map(s => h('li', {}, s))),
      stop.tell_client && h('p', { class: 'tell' }, h('strong', {}, 'Tell her: '), stop.tell_client),
    ),
  );
}

// Facts the ✓ row already covers, or that every pick has by rule.
const FACTS_IN_CHECKS = new Set(['speaks_client_language', 'in_dc', 'accepts_medicaid', 'within_3_miles', 'in_person']);
const GLANCE_FACTS = 3;

function providerCard(c, pick, stop, benefitsById) {
  const tier = TIER[pick.tier] || { label: `Tier ${pick.tier}`, hint: '' };
  const basis = pick.tier_basis || {};
  const check = (ok, yes, no) => h('span', { class: `check ${ok ? 'ok' : 'no'}` }, h('span', { 'aria-hidden': 'true' }, ok ? '✓' : '✗'), ` ${ok ? yes : no}`);
  const site = safeUrl(pick.website);
  const grade = stop && stop.grade;
  const extra = (pick.facts || []).filter(f => !FACTS_IN_CHECKS.has(f.code));
  const items = [
    ...(pick.questions || []).map(q => ({ key: q.code, text: q.text })),
    ...(pick.extra_questions || []).map((t, i) => ({ key: `x${i}.${t.slice(0, 40)}`, text: t, ai: true })),
  ];
  const countText = () => `${askedCount(c.id, pick.provider_id, items)} of ${items.length} asked`;
  const counter = h('span', { class: 'fold-sum' }, countText());
  const asks = checklist(c.id, pick.provider_id, items, () => { counter.textContent = countText(); });
  return h('li', { class: `provider${grade === 'not_realistic' ? ' dim' : ''}` },
    h('div', { class: 'provider-head' },
      h('span', { class: 'rank', title: `Match rank ${pick.rank}` }, `#${pick.rank}`),
      h('div', { class: 'provider-title' },
        h('h3', {}, pick.name),
        h('div', { class: 'case-sub' }, [pick.distance_mi != null && `${pick.distance_mi} mi`, pick.state !== 'DC' && pick.state, pick.telehealth && 'also telehealth'].filter(Boolean).join(' · ')),
      ),
      h('div', { class: 'provider-badges' },
        h('span', { class: `tier tier-${pick.tier}`, title: tier.hint }, tier.label),
        gradeBadge(grade),
      ),
    ),
    h('div', { class: 'glance' },
      check(basis.language_match, 'Her language', 'Interpreter needed'),
      check(basis.in_dc, 'In DC', `Outside DC`),
      check(basis.coverage_match, 'Coverage fits', 'Coverage to confirm'),
      extra.slice(0, GLANCE_FACTS).map(f => h('span', { class: 'chip chip-fact' }, f.text)),
      extra.length > GLANCE_FACTS && h('span', { class: 'chip' }, `+${extra.length - GLANCE_FACTS}`),
    ),
    h('div', { class: 'contact' },
      pick.phone && h('a', { href: telHref(pick.phone) }, `☎ ${pick.phone}`),
      pick.intake_phone && pick.intake_phone !== pick.phone && h('a', { href: telHref(pick.intake_phone) }, `Intake ${pick.intake_phone}`),
      site && h('a', { href: site, target: '_blank', rel: 'noopener noreferrer' }, 'Website'),
    ),
    fold(`${c.id}|${pick.provider_id}|ask`, 'ask',
      [h('span', { class: 'label' }, 'Call checklist'), counter],
      asks,
      pick.address && h('p', { class: 'muted' }, pick.address),
      (pick.facts || []).length > 0 && h('div', { class: 'sub' }, h('div', { class: 'label' }, 'From the listing'),
        h('div', { class: 'chips' }, pick.facts.map(f => h('span', { class: 'chip chip-fact' }, f.text)))),
      aiNote(pick.why, 'Why this pick'),
    ),
    tripSection(c, pick, stop, benefitsById),
  );
}

function sortToggle(c, active) {
  const btn = (key, text) => h('button', {
    type: 'button', class: 'seg', 'aria-pressed': active === key ? 'true' : 'false',
    onclick: () => { sortBy = key; route(); document.querySelector('.seg[aria-pressed="true"]')?.focus(); },
  }, text);
  return h('div', { class: 'sort', role: 'group', 'aria-label': 'Sort providers' },
    h('span', { class: 'label' }, 'Sort'), btn('reach', 'Easiest to reach'), btn('fit', 'Best fit'));
}

function providersBody(c, entry) {
  const { match } = entry;
  if (match instanceof Error) {
    return [h('div', { class: 'error' }, h('strong', {}, 'Could not read the provider match. '), match.message)];
  }
  if (!match) {
    return [h('section', { class: 'card empty-run' },
      h('h3', {}, 'No provider match yet'),
      h('p', {}, 'Run a match for this case, then reload this page:'),
      h('pre', {}, `python -m match ${c.id}            # scripted, offline\npython -m match ${c.id} --live     # with AI`),
    )];
  }

  // A trip plan is joined only when it came from the same run as the match.
  let trip = entry.trip;
  let tripNote = null;
  if (trip && !(trip instanceof Error) && trip.correlation_id !== match.correlation_id) {
    tripNote = h('p', { class: 'notice' }, 'The saved trip plan is from an earlier match, so it is not shown. Run ',
      h('code', {}, `python -m trip ${c.id}`), ' to plan trips for these providers.');
    trip = null;
  }
  const stops = new Map(((trip && trip.plans) || []).map(s => [s.provider_id, s]));
  const benefitsById = Object.fromEntries(((trip && trip.benefits) || []).map(b => [b.program_id, b]));
  const hasTrip = Boolean(trip);
  const order = hasTrip ? (sortBy || 'reach') : 'fit';

  let picks = [...(match.picks || [])];
  if (order === 'reach') {
    const pos = new Map((trip.plans || []).map(s => [s.provider_id, s.order]));
    picks.sort((a, b) => (pos.get(a.provider_id) ?? 1e9) - (pos.get(b.provider_id) ?? 1e9) || a.rank - b.rank);
  } else {
    picks.sort((a, b) => a.rank - b.rank);
  }
  // Sorted by reach, picks she can't realistically get to fold into one group at the end.
  const far = order === 'reach' ? picks.filter(p => (stops.get(p.provider_id) || {}).grade === 'not_realistic') : [];
  const near = picks.filter(p => !far.includes(p));
  const cards = list => h('ol', { class: 'providers' }, list.map(p => providerCard(c, p, stops.get(p.provider_id), benefitsById)));

  const k = match.counts || {};
  const changed = changedSinceMatch(c, match.needs);
  return [
    h('div', { class: 'run-line' },
      h('span', {}, `Matched ${match.date}`),
      h('span', { class: `mode mode-${match.mode}` }, MODE[match.mode] || match.mode),
      h('span', { class: 'muted' }, [
        k.A != null && `${k.A} strong`, k.B != null && `${k.B} possible`,
        k.C != null && `${k.C} need an interpreter`, k.excluded != null && `${k.excluded} ruled out`,
      ].filter(Boolean).join(' · ')),
    ),
    match.fallback_reason && h('p', { class: 'notice' }, `The AI step was skipped, so these picks come from the rules alone (${match.fallback_reason}).`),
    changed.length > 0 && h('p', { class: 'notice' },
      `This case changed after the match (${changed.join(', ')}). Rerun `, h('code', {}, `python -m match ${c.id}`), ' for current results.'),
    tripNote,
    benefitStrip(c, trip || (entry.trip instanceof Error ? entry.trip : null)),
    h('div', { class: 'list-bar' },
      h('h3', {}, plural(picks.length, 'provider to call', 'providers to call')),
      hasTrip && sortToggle(c, order),
    ),
    picks.length ? (near.length ? cards(near) : null) : h('p', { class: 'empty' }, 'No provider met the matching rules for this case.'),
    far.length > 0 && fold(`${c.id}|far`, 'group',
      [h('span', { class: 'label' }, `Not realistic to reach (${far.length})`), h('span', { class: 'fold-sum' }, far.map(p => p.name.split(' — ')[0]).join(' · '))],
      cards(far)),
    match.not_chosen_note && fold(`${c.id}|others`, 'group',
      [h('span', { class: 'label' }, 'Others considered'), h('span', { class: 'ai-tag' }, 'AI note, not checked')],
      h('p', { class: 'muted' }, match.not_chosen_note)),
    h('p', { class: 'run-meta' }, [
      `Rules ${match.rule_version}`, `data ${match.data_version}`,
      match.prompt_version && `prompt ${match.prompt_version}`, `run ${match.correlation_id}`,
    ].filter(Boolean).join(' · ')),
  ];
}

// ---------- routing ----------

function renderDetail(c, missingId, tab) {
  const detail = document.getElementById('detail');
  if (!c) {
    detail.replaceChildren(h('p', { class: 'empty' }, missingId ? `No case with id “${missingId}”.` : 'Select a case to see details.'));
    return;
  }
  const back = h('button', { class: 'back', type: 'button', onclick: () => { location.hash = ''; } }, '← All cases');
  if (tab === 'case') {
    // Optional parts may be null/false; replaceChildren would print them, so drop them.
    detail.replaceChildren(...[back, header(c, tab), ...caseBody(c)].filter(Boolean));
    return;
  }
  const token = ++renderToken;
  const cached = runs.get(c.id);
  if (cached) {
    detail.replaceChildren(...[back, header(c, tab), ...providersBody(c, cached)].filter(Boolean));
    return;
  }
  detail.replaceChildren(back, header(c, tab), h('p', { class: 'empty' }, 'Loading provider match…'));
  runsFor(c.id).then(entry => {
    if (token !== renderToken) return; // the user moved on
    const focused = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.tab;
    detail.replaceChildren(...[back, header(c, tab), ...providersBody(c, entry)].filter(Boolean));
    if (focused) document.querySelector(`.tab[data-tab="${focused}"]`)?.focus();
    document.getElementById('status').textContent = entry.match && !(entry.match instanceof Error)
      ? `${plural((entry.match.picks || []).length, 'provider', 'providers')} for ${fullName(c)}`
      : `No provider match for ${fullName(c)}`;
  });
}

function parseHash() {
  const m = location.hash.match(/^#\/case\/([^/]+)(\/providers)?\/?$/);
  if (!m) return { id: null, tab: 'case' };
  let id = m[1];
  try { id = decodeURIComponent(id); } catch { /* keep raw */ }
  return { id, tab: m[2] ? 'providers' : 'case' };
}

const isPhone = () => window.matchMedia && window.matchMedia('(max-width: 760px)').matches;

function route(event) {
  const { id: fromHash, tab } = parseHash();
  const c = cases.find(x => x.id === fromHash) || (fromHash ? null : cases[0]);
  // On phones the detail pane shows whenever a case was asked for, found or not.
  document.getElementById('layout').classList.toggle('has-selection', Boolean(fromHash));
  // Remember which tab had focus so it can be restored after the pane is rebuilt.
  const focusedTab = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.tab;
  if (event) renderToken++;
  markSelected(c && c.id);
  renderDetail(c, fromHash, c ? tab : 'case');
  const view = tab === 'providers' ? ' · Providers' : '';
  document.title = fromHash ? `CareBridge · ${c ? fullName(c) + view : 'Case not found'}` : 'CareBridge · Cases';
  document.getElementById('status').textContent = c ? `Showing ${fullName(c)}${view}` : fromHash ? 'Case not found' : '';
  if (focusedTab) document.querySelector(`.tab[data-tab="${focusedTab}"]`)?.focus();
  // The list is hidden on phones once a case opens, so move focus to the case title.
  else if (event && fromHash && c && isPhone()) document.getElementById('case-title').focus();
}

// ---------- theme: auto (system), light or dark; remembered in this browser ----------
const THEMES = ['auto', 'light', 'dark'];
function applyTheme(t) {
  const root = document.documentElement;
  if (t === 'auto') delete root.dataset.theme; else root.dataset.theme = t;
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.textContent = `Theme: ${cap(t)}`;
    btn.setAttribute('aria-label', `Color theme: ${t}. Change theme`);
  }
}
function setupTheme() {
  let t = 'auto';
  try { t = THEMES.includes(localStorage.getItem('carebridge.theme')) ? localStorage.getItem('carebridge.theme') : 'auto'; } catch { /* default */ }
  applyTheme(t);
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    t = THEMES[(THEMES.indexOf(t) + 1) % THEMES.length];
    try { t === 'auto' ? localStorage.removeItem('carebridge.theme') : localStorage.setItem('carebridge.theme', t); } catch { /* not saved */ }
    applyTheme(t);
  });
}

async function init() {
  setupTheme();
  try {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    cases = await res.json();
    if (!Array.isArray(cases)) throw new Error('cases.json is not a list');
  } catch (err) {
    document.getElementById('layout').classList.add('has-selection');
    document.getElementById('detail').replaceChildren(h('div', { class: 'error' },
      h('strong', {}, 'Could not load cases. '), `${err.message}. Serve the repo root, for example `,
      h('code', {}, 'python3 -m http.server 8000'), ', then open ', h('code', {}, '/ui/'), '.'));
    return;
  }
  buildList();
  window.addEventListener('hashchange', route);
  route();
}

init();
