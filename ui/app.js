// CareBridge case page. Reads the synthetic cases and renders a case list plus
// the selected case. Case data is rendered as text only (never as HTML).
const DATA_URL = '../data/cases.json';

const CARE_MODE = {
  in_person: 'In person only',
  in_person_preferred: 'In person preferred',
  telehealth: 'Telehealth',
  telehealth_preferred: 'Telehealth preferred',
  either: 'In person or telehealth',
};
const ENGLISH = { none: 'No English', basic: 'Basic English', intermediate: 'Some English', fluent: 'Fluent English' };

let cases = [];

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

// Short flags for the list card and the "what she needs" row.
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
  document.getElementById('case-count').textContent = `${cases.length} ${cases.length === 1 ? 'case' : 'cases'}`;
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

function renderDetail(c, missingId) {
  const detail = document.getElementById('detail');
  if (!c) {
    detail.replaceChildren(h('p', { class: 'empty' }, missingId ? `No case with id “${missingId}”.` : 'Select a case to see details.'));
    return;
  }
  const pref = c.preferences || {};
  const hh = c.household || {};
  const kids = Array.isArray(c.children)
    ? (c.children.length ? c.children.map(k => (k && k.age != null ? `${k.age} yrs` : 'age unknown')).join(', ') : 'None')
    : null;
  const cw = c.caseworker || {};

  // Optional parts may be null/false; replaceChildren would print them, so drop them.
  detail.replaceChildren(...[
    h('button', { class: 'back', type: 'button', onclick: () => { location.hash = ''; } }, '← All cases'),
    h('div', { class: 'detail-head' },
      h('div', { class: 'detail-title' },
        h('span', { class: 'avatar', 'aria-hidden': 'true' }, initials(c)),
        h('div', {},
          h('h2', { tabindex: '-1', id: 'case-title' }, fullName(c)),
          h('div', { class: 'case-sub' }, [c.age && `${c.age} years old`, c.id, c.synthetic && 'synthetic'].filter(Boolean).join(' · ')),
        ),
        urgencyPill(c),
      ),
      c.mental_health_concerns && h('p', { class: 'concern' }, c.mental_health_concerns),
      h('div', { class: 'contact' },
        c.phone && h('span', {}, `☎ ${c.phone}`),
        c.address && h('span', {}, c.address),
      ),
      h('div', { class: 'needs' },
        h('div', { class: 'label' }, 'Needs from care'),
        h('div', { class: 'chips' }, needs(c).map(chip)),
      ),
      h('div', { class: 'actions' },
        h('button', { class: 'btn btn-primary', type: 'button', disabled: true, title: 'Provider match is being built' }, 'Find providers'),
        h('span', { class: 'hint' }, 'Provider match is coming next.'),
      ),
    ),
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
  ].filter(Boolean));
}

function selectedFromHash() {
  const m = location.hash.match(/^#\/case\/(.+)$/);
  if (!m) return null;
  try { return decodeURIComponent(m[1]); } catch { return m[1]; }
}

const isPhone = () => window.matchMedia && window.matchMedia('(max-width: 760px)').matches;

function route(event) {
  const fromHash = selectedFromHash();
  const c = cases.find(x => x.id === fromHash) || (fromHash ? null : cases[0]);
  // On phones the detail pane shows whenever a case was asked for, found or not.
  document.getElementById('layout').classList.toggle('has-selection', Boolean(fromHash));
  markSelected(c && c.id);
  renderDetail(c, fromHash);
  document.title = fromHash ? `CareBridge · ${c ? fullName(c) : 'Case not found'}` : 'CareBridge · Cases';
  document.getElementById('status').textContent = c ? `Showing ${fullName(c)}` : fromHash ? 'Case not found' : '';
  // The list is hidden on phones once a case opens, so move focus to the case title.
  if (event && fromHash && c && isPhone()) document.getElementById('case-title').focus();
}

async function init() {
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
