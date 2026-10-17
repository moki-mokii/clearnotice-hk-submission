/* All notice/model strings are rendered as text, never as HTML. */
'use strict';
const $ = (id) => document.getElementById(id);
const labels = JSON.parse($('config').dataset.labels);
const disclaimers = JSON.parse($('config').dataset.disclaimers);
const keys = ['subject','audience','event_time','registration_deadline','location','fee','method','conditions'];
let revision = 0, pending = false, current = null, cardText = "", inputMode = "url", importing = false, imported = null;

function node(tag, text, className) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
}
function status(text, kind = '') { document.querySelector('.result-panel').hidden = false; $('status').hidden = !text; $('status').textContent = text; $('status').className = `status ${kind}`; }
function setExport(enabled) { $('copy').disabled = !enabled; $('print').disabled = !enabled; if ($('copy-full')) $('copy-full').disabled = !enabled; }
function changed() {
  revision++;
  $('count').textContent = `${[...normalize($('notice').value)].length} / 12,000`;
  if (current || pending) {
    current = null; cardText = ''; setExport(false); $('result').hidden = true; $('empty-state').hidden = false;
    $('copy-fallback').hidden = true; $('copy-text').value = ''; $('print-content').textContent = '';
    $('source-dialog').close(); $('result-tools').hidden = true; document.body.classList.remove('has-result'); expandInput(true);
    status('內容已變更，請重新解讀。' + (pending ? ' 正在等候上一個請求結束。' : ''), 'busy');
  }
}
function normalize(text) { return text.replace(/\r\n?/g, '\n').normalize('NFC').trim(); }
['notice','language','source-label','source-url','notice-url'].forEach(id => $(id).addEventListener('input', changed));
function importStatus(text, error=false) {
  $('import-status').textContent = text; $('import-status').hidden = !text;
  $('import-status').className = error ? 'import-error' : 'subtle';
}
function chooseInput(mode) {
  if (mode === inputMode) return;
  inputMode = mode; changed();
  $('choose-url').setAttribute('aria-pressed',String(mode === 'url'));
  $('choose-text').setAttribute('aria-pressed',String(mode === 'text'));
  $('url-input-panel').hidden = mode !== 'url'; $('notice-url').disabled = mode !== 'url';
  $('source-options').hidden = mode !== 'text'; $('source-url').disabled = mode !== 'text';
  if ($('url-privacy-note')) $('url-privacy-note').hidden = mode !== 'url';
  $('text-input-panel').hidden = mode === 'url' && !imported;
  $('notice').required = mode === 'text';
  $('analyze').hidden = mode === 'url' && !imported;
}
$('choose-url').addEventListener('click',()=>chooseInput('url'));
$('choose-text').addEventListener('click',()=>chooseInput('text'));
$('notice-url').addEventListener('input',()=>{
  imported = null; importStatus('');
  if (inputMode === 'url') { $('text-input-panel').hidden = true; $('analyze').hidden = true; }
});
$('read-url').addEventListener('click', async()=>{
  if (importing || pending) return;
  const url = $('notice-url').value.trim();
  try { const u = new URL(url); if (!['http:','https:'].includes(u.protocol)) throw Error(); }
  catch (_) { importStatus('請貼上完整的 http 或 https 網頁連結。',true); $('notice-url').focus(); return; }
  changed(); const version = revision; imported = null;
  importing = true; $('read-url').disabled = true; $('analyze').disabled = true;
  importStatus('正在讀取網頁……');
  const controller = new AbortController(), timeout = setTimeout(()=>controller.abort(),25000);
  try {
    const response = await fetch('/api/import-url',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({url})});
    const data = await response.json();
    if (revision !== version) return;
    if (!response.ok) throw Error(`${data.error?.message || '讀取失敗，請改貼文字。'}（${data.error?.code || response.status}）`);
    $('notice').value = data.text; $('source-label').value = data.source_label.slice(0,120); $('source-url').value = data.source_url;
    changed(); imported = data;
    $('text-input-panel').hidden = false; $('analyze').hidden = false;
    importStatus(data.notice + ' 確認後按「生成重點卡片」。');
    $('notice').focus();
  } catch(error) {
    if (revision !== version) return;
    importStatus(error.name === 'AbortError' ? '讀取逾時，請重試或改貼文字。' : error.message,true);
  } finally {
    clearTimeout(timeout); importing = false; $('read-url').disabled = false; $('analyze').disabled = pending;
    if (revision !== version && !imported) importStatus('輸入已變更，請重新讀取連結。');
  }
});
document.querySelectorAll('.example').forEach(button => button.addEventListener('click', () => {
  chooseInput('text'); imported = null;
  $('notice').value = button.dataset.text; $('source-label').value = `虛構示例：${button.dataset.title}`;
  $('source-url').value = ''; changed();
  if (!pending) status('已載入虛構示例，按「生成重點卡片」開始。');
  $('notice').rows = 10; $('notice').focus(); $('notice').setSelectionRange(0,0); $('notice').scrollTop = 0;
}));
function expandInput(expand) {
  $('notice-form').hidden = !expand; $('input-collapsed').hidden = expand;
  $('edit-notice').hidden = !current; $('edit-notice').setAttribute('aria-expanded', String(expand));
  $('edit-notice').textContent = expand ? '收起原文' : '修改通知';
}
$('edit-notice').addEventListener('click', () => {
  const expand = $('notice-form').hidden; expandInput(expand);
  if (expand) $('notice').focus();
});
function showSource(items = [], context = '', fullField = false) {
  $('source-context').textContent = context;
  $('source-dialog').classList.toggle('field-detail-mode',fullField);
  document.querySelectorAll('.highlight').forEach(n => n.classList.remove('highlight'));
  if (!$('source-dialog').open) $('source-dialog').showModal();
  items.forEach(e => $(`source-${e.line_id}`)?.classList.add('highlight'));
  if (fullField) { $('source-dialog').scrollTop = 0; $('close-source').focus({preventScroll:true}); return; }
  const target = items.length ? $(`source-${items[0].line_id}`) : $('source-lines');
  if (target) { target.scrollIntoView({block:'center'}); if (items.length) target.focus({preventScroll:true}); }
}
$('open-source').addEventListener('click', () => showSource());
$('close-source').addEventListener('click', () => $('source-dialog').close());
function evidence(items, en) {
  const b = node('button', en ? 'Check source' : '核對依據', 'source-link'); b.type = 'button';
  b.addEventListener('click', () => showSource(items)); return b;
}
function section(title) { const s = node('section', undefined, 'result-section'); s.append(node('h3', title)); return s; }
function noticeKind(facts) {
  // Presentation grouping only: uncertain fields and stated conditions are never hidden.
  const subject = facts.subject.value || '';
  if (/暫停|停服|取消|關閉|維護|suspend|closure|closed|cancel|maintenance/i.test(subject)) return 'service';
  if (/申請|入學|獎學金|allocation|application|scholarship/i.test(subject)) return 'application';
  if (/活動|講座|班|演奏|演出|嘉年華|導賞|運動會|展覽|workshop|concert|event|tour|class/i.test(subject)) return 'event';
  return 'notice';
}
function factValue(f, en) {
  return f.status === 'stated' ? f.value : f.status === 'missing' ?
    (en ? 'Not stated in the notice' : '原文未說明') : (en ? 'Needs checking with the source' : '需要核對原文');
}
function generatedTime(value, en) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(en ? 'en-GB' : 'zh-Hant-HK', {
    timeZone:'Asia/Hong_Kong', year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', hourCycle:'h23'
  }).format(date);
}
function distinctConditions(facts) {
  // Only exact complete clauses already visible elsewhere are removed; no paraphrase,
  // substring matching, number normalization or semantic guessing in the browser.
  const clauses = value => (value || '').split(/[；;。\n]/).map(x=>x.trim()).filter(Boolean);
  const covered = new Set(['audience','fee','event_time'].flatMap(key =>
    facts[key].status === 'stated' ? clauses(facts[key].value) : []));
  return clauses(facts.conditions.value).filter(text=>!covered.has(text)).join('；');
}
function compactSchedule(value, kind) {
  // Extract whole clauses only. Every omitted clause remains in an adjacent disclosure.
  // Service interruptions keep every window visible, including cross-midnight windows.
  if (kind === 'service' || !value || [...value].length < 90) return value;
  const clauses = value.split(/(?<=[。；;])\s*|(?<=[.!?])\s+(?=[A-Z])/u).filter(x=>x.trim());
  if (clauses.length < 2) return value;
  const mandatory = /必須|須於|須在|至少|不少於|不接受|不能|不得|暫停|關閉|恢復|歸還|must|required|at least|not accept|cannot|closed?|reopen|resum|return.*(?:by|before)/i;
  const keep = clauses.filter((clause,index)=>index===0 || mandatory.test(clause));
  return keep.length === clauses.length ? value : keep.join(' ').trim();
}
function render(payload) {
  const en = payload.meta.output_language === 'en', lang = payload.meta.output_language, r = payload.result;
  const compact = r.card || null, cardFacts = compact ? compact.facts : r.facts;
  const introduction = compact ? compact.overview : r.summary[0];
  const container = $('result'); container.replaceChildren(); container.lang = lang;
  document.body.classList.add('has-result');
  const kind = noticeKind(r.facts), typeNames = {service:en?'Service update':'服務變更',application:en?'Application':'申請辦理',event:en?'Activity':'活動通知',notice:en?'Notice':'通知重點'};
  const complexNotice = [...payload.source.text].length > 600 || r.actions.length >= 4 ||
    (kind === 'application' && Object.values(r.facts).reduce((n,f)=>n+[...(f.value||'')].length,0)>350);
  const card = node('article',undefined,'notice-card'); card.id = 'action-card';
  const top = node('div',undefined,'card-top'); top.append(node('span',typeNames[kind],'card-type'));
  if (payload.meta.mode === 'fixture') top.append(node('span',en?'Fictional example · fixed result':'虛構示例 · 固定結果','fixture-label'));
  card.append(top);
  const title = cardFacts.subject.status === 'stated' ? cardFacts.subject.value : (en?'Notice at a glance':'通知重點');
  const heading = node('h2',title,'card-title'); card.append(heading);
  if (cardFacts.subject.evidence.length) heading.append(evidence(cardFacts.subject.evidence,en));
  const intro = node('div',undefined,'card-intro');
  intro.append(node('p',introduction.text),evidence(introduction.evidence,en));
  const briefService = kind === 'service' && [...payload.source.text].length <= 300 &&
    !Object.values(r.facts).some(f=>f.status==='uncertain');
  const keyFacts = ['subject','audience','registration_deadline','fee','conditions'].map(k=>r.facts[k].value||'').join(' ');
  const allocation = /拍賣|競投|抽籤|auction|bidding|lottery/i;
  const essentialIntro = allocation.test(r.summary[0].text) && !allocation.test(keyFacts);
  const foldExplanation = briefService || (!compact && complexNotice && r.facts.subject.status==='stated' &&
    !Object.values(r.facts).some(f=>f.status==='uncertain') && !essentialIntro);
  if (foldExplanation) {
    const explanation = node('details',undefined,'brief-explanation');
    explanation.append(node('summary',en?'Read plain-language explanation':'閱讀通俗說明'),intro); card.append(explanation);
  } else card.append(intro);
  // Promote a supported funding explanation without relabelling a grant as a fee.
  const funding = /funding|資助|獎學金/i.test(cardFacts.fee.value||'') ? null : r.summary.slice(1).find(item =>
    /funding ceiling|funding.*HK\$|資助上限|資助額|獎學金上限/i.test(item.text) && /\d|[一二三四五六七八九十百千萬億]+元/.test(item.text));
  if (funding) {
    const note = section(en?'Funding':'資助金額'); note.classList.add('funding-note');
    note.append(node('p',funding.text),evidence(funding.evidence,en)); card.append(note);
  }
  const importantMissing = kind === 'service' ? ['event_time'] : kind === 'application' ? ['audience','registration_deadline','method','fee'] : kind === 'event' ? ['event_time','location','fee'] : ['event_time','fee'];
  const displayFacts = {...cardFacts};
  if (!compact && complexNotice && r.facts.event_time.status==='stated') {
    displayFacts.event_time = {...r.facts.event_time,value:compactSchedule(r.facts.event_time.value,kind)};
  }
  if (cardFacts.conditions.status === 'stated') displayFacts.conditions = {...cardFacts.conditions,value:distinctConditions(cardFacts)};
  const visibleKeys = ['registration_deadline','event_time','audience','location','fee','method','conditions'].filter(k =>
    (r.facts[k].status !== 'missing' || importantMissing.includes(k)) && !(k === 'conditions' && displayFacts.conditions.value === ''));
  const shortLabels = en ? {registration_deadline:'Apply by',event_time:'When',audience:'Who',location:'Where',fee:'Cost',method:'How',conditions:'Please note'} : {registration_deadline:'報名／申請截止',event_time:'時間',audience:'對象',location:'地點',fee:'費用',method:'辦理方式',conditions:'參加前留意'};
  if (!en && kind !== 'event') shortLabels.conditions = kind === 'application'?'申請須知':'請留意';
  if (/資助額|資助金額|獎學金|funding|scholarship|fellowship/i.test(cardFacts.fee.value || '')) shortLabels.fee = en?'Funding / costs':'資助／費用';
  const rows = node('dl',undefined,'card-facts');
  const procedureRows = node('dl',undefined,'card-facts');
  visibleKeys.forEach(key => {
    const f = displayFacts[key], row = node('div',undefined,`card-row ${f.status} ${key === 'conditions' ? 'conditions-row' : ''}`);
    row.dataset.field = key;
    const term = node('dt',shortLabels[key]); row.append(term);
    const value = node('dd');
    const content = node('div',undefined,'fact-content');
    if (f.evidence.length) {
      const button = node('button',factValue(f,en),'fact-value'); button.type = 'button';
      button.setAttribute('aria-label',`${shortLabels[key]}: ${factValue(f,en)} — ${en?'check source':'核對原文'}`);
      button.addEventListener('click', () => showSource(f.evidence,shortLabels[key])); content.append(button);
    } else content.append(node('span',factValue(f,en)));
    if (f.status==='stated' && f.value!==r.facts[key].value) {
      const more = node('button',en?'Full':'完整','field-more'); more.type='button';
      more.setAttribute('aria-label',en?`Full ${shortLabels[key].toLowerCase()} and restrictions`:`查看完整${shortLabels[key]}與限制`);
      more.addEventListener('click',()=>showSource(r.facts[key].evidence,`${shortLabels[key]}：${r.facts[key].value}`,true));
      term.append(more);
    }
    value.append(content); row.append(value);
    const procedural = f.status === 'stated' && (
      (key === 'event_time' && kind === 'application' && /assess|評審/i.test(f.value)) ||
      (key === 'location' && (kind === 'application' || [...f.value].length > 100)) ||
      (key === 'method' && (r.actions.length > 0 || [...f.value].length > 80)));
    (procedural ? procedureRows : rows).append(row);
  }); card.append(rows);
  if (compact && cardFacts.method.status==='stated') {
    const exceptions=cardFacts.method.value.split(/(?<=[；;。])\s*|(?<=[.!?])\s+(?=[A-Z])/u)
      .filter(clause=>/no prior application|no preregistration|no pre-registration|no advance booking|(?:毋須|無須).*(?:申請|登記|報名)/i.test(clause));
    if(exceptions.length && procedureRows.querySelector('[data-field=method]')) {
      const exception=section(en?'Booking exception':'特別安排');exception.classList.add('booking-exception');
      exception.append(node('p',exceptions.join(' ')),evidence(cardFacts.method.evidence,en));card.append(exception);
    }
  }
  // A later confirmation deadline must not disappear behind the step disclosure.
  // Promote the complete supported step only if its literal interval is absent from
  // the visible facts; never rewrite a number or infer an approval requirement.
  const mainFactText = visibleKeys.filter(k=>!procedureRows.querySelector(`[data-field="${k}"]`))
    .map(k=>displayFacts[k].value || '').join(' ');
  const confirmationReminders = r.actions.slice(1).filter(item=>{
    if (!/確認|confirm/i.test(item.text)) return false;
    const cue = item.text.match(/[一二三四五六七八九十百\d]+個?(?:工作)?(?:天|日|小時)|(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:(?:working|business)\s+)?(?:days?|hours?)/i);
    return cue && !mainFactText.includes(cue[0]);
  });
  if (confirmationReminders.length) {
    const reminder = section(en?'Confirmation deadline':'確認期限'); reminder.classList.add('confirmation-note');
    confirmationReminders.forEach(item=>reminder.append(node('p',item.text),evidence(item.evidence,en)));card.append(reminder);
  }
  const actions = section(en?'Your next step':'你需要做什麼'); actions.classList.add('next-step');
  const ol = node('ol'); const later = node('ol');
  const previewCount = Math.min(1,r.actions.length);
  later.start = previewCount + 1;
  r.actions.forEach((item,index) => {
    const preview = index===0 && compact?.next_step ? compact.next_step : item;
    const li = node('li'); li.append(node('span',preview.text));
    if(preview.text!==item.text){
      const full=node('button',en?'Full step & source':'完整步驟與依據','source-link');full.type='button';
      full.addEventListener('click',()=>showSource(item.evidence,item.text,true));li.append(full);
    } else li.append(evidence(preview.evidence,en));
    (index < previewCount ? ol : later).append(li);
  });
  if (r.actions.length) actions.append(ol);
  else actions.append(node('p',en?'No required steps stated in the notice.':'原文未列出需要辦理的步驟。'));
  if (r.actions.length > previewCount) {
    const remaining = node('details',undefined,'later-steps');
    remaining.append(node('summary',en?`View all remaining steps (${r.actions.length-previewCount})`:`查看其餘辦理步驟（${r.actions.length-previewCount}項）`),later); actions.append(remaining);
  }
  if (r.actions.length) card.append(actions);
  if (procedureRows.childElementCount) {
    const procedure = node('details',undefined,'procedure-details method-details');
    procedure.append(node('summary',en?'Detailed schedules, locations & methods':'詳細時間、地點與辦理安排'),procedureRows);
    card.append(procedure);
  }
  const attention = payload.warnings.filter(w => w.code !== 'CHECK_WITH_ORGANIZER');
  if (attention.length) {
    const note = node('div',undefined,'attention'); note.append(node('strong',en?'Please check':'請留意'));
    [...new Set(attention.map(w=>w.message))].forEach(message=>note.append(node('p',message))); card.append(note);
  }
  // An uncertain compact field may have useful multi-session information in the overview.
  if (['event_time','location','fee'].some(k => r.facts[k].status === 'uncertain')) {
    const note = section(en?'Details to check':'待核對的補充資訊'); note.classList.add('attention');
    r.summary.slice(1).forEach(item => { note.append(node('p',item.text),evidence(item.evidence,en)); });
    if (r.summary.length > 1) card.append(note);
  }
  const sourceLabel = $('source-label').value.trim() || (en?'User-provided notice':'使用者提供的通知');
  card.append(node('p',`${en?'Source':'來源'}：${sourceLabel}`,'card-source'));
  card.append(node('p',en?'Confirm important dates, fees and eligibility with the original notice.':'重要日期、費用及資格，請核對原通知。','result-note'));
  container.append(card);
  if (imported && inputMode === 'url') card.append(node('p',en?'Imported webpage text; images, attachments and linked pages are not included.':'網頁文字擷取；未包含圖片、附件及連結內頁。','result-note'));
  const detail = node('details',undefined,'full-details'); detail.append(node('summary',en?'Full explanation & generation details':'完整解讀與生成詳情'));
  const overview = section(en?'Overview':'完整概覽'); r.summary.forEach(item => overview.append(node('p',item.text),evidence(item.evidence,en))); detail.append(overview);
  const fullFacts = section(en?'All eight fields':'全部八個欄位');
  keys.forEach((key,i) => {
    const row = node('p',`${labels[lang][i]}：${factValue(r.facts[key],en)}`);
    if (r.facts[key].evidence.length) row.append(evidence(r.facts[key].evidence,en)); fullFacts.append(row);
  }); detail.append(fullFacts);
  if (r.actions.length) {
    const allActions = section(en?'All steps':'完整辦理步驟'); const list = node('ol');
    r.actions.forEach(item => { const li = node('li',item.text); li.append(evidence(item.evidence,en)); list.append(li); });
    allActions.append(list); detail.append(allActions);
  }
  if (payload.warnings.length) {
    const checks = section(en?'Checks':'核對提示'); const list = node('ul');
    payload.warnings.forEach(w => list.append(node('li',w.message))); checks.append(list); detail.append(checks);
  }
  const m = payload.meta;
  if (imported && inputMode === 'url') detail.append(node('p',`${en?'Page retrieved':'網頁讀取時間'}: ${imported.retrieved_at}`,'result-meta'));
  detail.append(node('p',`${m.mode} · ${m.model} · ${m.latency_ms} ms · ${m.generated_at} · ${m.prompt_version}`,'result-meta'));
  detail.append(node('p',en?'Matching source quotes does not verify the interpretation.':'引句匹配不代表解釋已獲語義驗證。','result-note'));
  const fullCopy = node('button',en?'Copy full result and source':'複製完整結果與原文'); fullCopy.id = 'copy-full'; fullCopy.type = 'button';
  fullCopy.addEventListener('click',()=>copyResult(true)); detail.append(fullCopy); container.append(detail);
  $('source-lines').replaceChildren();
  payload.source.lines.forEach(line => {
    const row = node('div',undefined,'source-line'); row.id = `source-${line.line_id}`; row.tabIndex = -1;
    row.append(node('span',line.line_id,'line-id'),node('span',line.text || ' ','line-text')); $('source-lines').append(row);
  });
  const exportLines = ['明白通 ClearNotice HK', typeNames[kind], title, '', r.summary[0].text, ''];
  if (funding) exportLines.push(`${en?'Funding':'資助金額'}：${funding.text}`);
  if (m.mode === 'fixture') exportLines.splice(1,0,en?'Fictional example · fixed result':'虛構示例 · 固定結果');
  visibleKeys.forEach(key => exportLines.push(`${shortLabels[key]}：${factValue(r.facts[key],en)}`));
  if (r.actions.length) exportLines.push('',en?'Your next step':'你需要做什麼',...r.actions.map((x,i)=>`${i+1}. ${x.text}`));
  if (attention.length) exportLines.push(...attention.map(w=>w.message));
  if (['event_time','location','fee'].some(k => r.facts[k].status === 'uncertain')) exportLines.push(...r.summary.slice(1).map(x=>x.text));
  exportLines.push('',`${en?'Source':'來源'}：${sourceLabel}`, ...( $('source-url').value.trim() ? [$('source-url').value.trim()] : []),`${en?'Generated (Hong Kong time)':'生成時間（香港時間）'}：${generatedTime(m.generated_at,en)}`,disclaimers[lang]);
  if (imported && inputMode === 'url') exportLines.push(en?'Imported webpage text only; attachments and linked pages not included.':'僅擷取網頁文字，未包含附件和連結內頁。');
  cardText = exportLines.join('\n');
  $('empty-state').hidden = true; container.hidden = false; $('result-tools').hidden = false;
  $('open-source').textContent = en?'Check source':'核對原文'; $('copy').textContent = en?'Copy card':'複製卡片'; $('print').textContent = en?'Print card':'列印卡片';
  setExport(true); $('print-content').textContent = cardText; expandInput(false); status('');
  card.tabIndex = -1; card.focus({preventScroll:true}); card.scrollIntoView({block:'start',behavior:'auto'});
}
$('notice-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pending || importing) return;
  if (inputMode === 'url' && !imported) { importStatus('請先讀取網頁並確認正文。',true); return; }
  const text = normalize($('notice').value), length = [...text].length;
  if (length < 30 || length > 12000) { status('請輸入30至12,000字的通知。','error'); $('notice').focus(); return; }
  const sourceURL = $('source-url').value.trim();
  if (sourceURL) { try { const u = new URL(sourceURL); if (!['http:','https:'].includes(u.protocol)) throw Error(); } catch (_) { status('來源網址只接受 http 或 https。','error'); return; } }
  current = null; cardText = ''; expandInput(true); setExport(false); $('result').hidden = true; $('source-dialog').close(); $('result-tools').hidden = true;
  $('copy-fallback').hidden = true; $('print-content').textContent = ''; $('empty-state').hidden = true;
  pending = true; const sentRevision = revision; $('analyze').disabled = true; $('analyze').textContent = '正在解讀……';
  status('正在整理重點及原文引句，請稍候（最多約65秒）。','busy');
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 70000);
  try {
    const response = await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
      body:JSON.stringify({text,output_language:$('language').value,source_label:$('source-label').value,source_url:sourceURL,input_kind:'pasted'})});
    const payload = await response.json();
    if (sentRevision !== revision) return;
    if (!response.ok) throw new Error(`${payload.error?.message || '解讀失敗，請重試。'}（${payload.error?.code || response.status}）`);
    current = payload; render(payload);
  } catch (error) {
    if (sentRevision !== revision) return;
    current = null; $('empty-state').hidden = false;
    status(error.name === 'AbortError' ? '等候逾時，原文已保留，請重試。' : `未能完成解讀：${error.message} 原文已保留。`,'error');
  } finally {
    clearTimeout(timeout); pending = false; $('analyze').disabled = false; $('analyze').textContent = '生成重點卡片 ↗';
    if (sentRevision !== revision) status('內容已變更，請重新解讀。','busy');
  }
});
async function copyResult(full = false) {
  if (!current) return; const text = full ? current.copy_text : cardText, version = revision;
  try { await navigator.clipboard.writeText(text); if (version === revision) status(full ? '已複製完整結果與原文。' : '已複製重點卡片。'); }
  catch (_) { if (version !== revision) return; $('copy-text').value = text; $('copy-fallback').hidden = false; $('copy-text').focus(); $('copy-text').select(); status('瀏覽器未能自動複製，請手動複製下方文字。','error'); }
}
$('copy').addEventListener('click',()=>copyResult());
$('print').addEventListener('click', () => { if (current) window.print(); });
