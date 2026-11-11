"""Self-contained offline review page. No server, external assets or API key."""

import base64
import json
from pathlib import Path

from docguard.ai.experiment_packet import load_labels, load_packet
from docguard.ai.files import ProposalError, digest, parse_json, read_bytes


def render_review_ui(
    packet: Path,
    output: Path,
    report: Path | None = None,
    *,
    labels_path: Path | None = None,
) -> None:
    packet_hash, data = load_packet(packet)
    bundle: dict[str, object] = {
        "packet": data,
        "packet_hash": packet_hash,
        "report": None,
        "report_hash": None,
        "labels": [],
    }
    if labels_path is not None:
        if report is not None:
            raise ProposalError("Preload labels only in the pre-generation review page")
        _, labels = load_labels(labels_path, packet_hash, data)
        bundle["labels"] = list(labels.values())
    if report is not None:
        raw = read_bytes(report, 100_000_000)
        experiment = parse_json(raw.decode("utf-8"))
        if (
            not isinstance(experiment, dict)
            or experiment.get("kind") != "docguard.experiment"
            or experiment.get("identity", {}).get("packet_sha256") != packet_hash
        ):
            raise ProposalError("Experiment must match the review packet")
        bundle.update(report=experiment, report_hash=digest(raw))
    if output.suffix.lower() != ".html":
        raise ProposalError("Review UI output must be an .html file")
    encoded = base64.b64encode(json.dumps(bundle, ensure_ascii=False).encode()).decode()
    with output.open("x", encoding="utf-8") as stream:
        stream.write(PAGE.replace("__BUNDLE__", encoded))


PAGE = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>DocGuard · Evidence review</title>
<style>
:root{font-family:system-ui,sans-serif;color:#17243b;background:#f3f5f8;line-height:1.5}body{margin:0}header{background:#12233d;color:white;padding:22px 4vw}header p{margin:4px 0;color:#cfdae9}main{max-width:1450px;margin:auto;padding:24px}h1{font-size:24px;margin:0}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px}.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:18px}.grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:20px}.card{background:white;border:1px solid #d8dfe8;border-radius:10px;padding:20px;margin-bottom:18px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#f6f8fa;padding:14px;max-height:480px;overflow:auto}label{display:block;margin:10px 0;font-weight:600}input[type=text],textarea,select{box-sizing:border-box;width:100%;padding:9px;border:1px solid #a4b0c0;border-radius:5px;font:inherit;background:white}textarea{min-height:110px}button,.upload{border:1px solid #aab8cb;background:white;color:#12233d;border-radius:6px;padding:9px 14px;font:inherit;cursor:pointer}button.primary{background:#225ce0;color:white;border:0}button:disabled{opacity:.5;cursor:default}.muted{color:#59677a;font-size:13px}.notice{padding:12px;background:#fff3d7;border-left:4px solid #c98c15}.status{font-size:13px;color:#23533a}.tags{font-family:monospace;font-size:12px;overflow-wrap:anywhere}a{color:#245bc9;margin-right:15px}details{border-top:1px solid #ddd;padding:10px 0}summary{cursor:pointer;font-weight:600}.buttons{display:flex;gap:8px;margin-top:14px}#error{color:#a10e23}#select{max-width:550px}#metrics{max-height:220px}footer{margin:20px 0;color:#59677a;font-size:13px}@media(max-width:850px){.grid{grid-template-columns:1fr}main{padding:14px}}
</style>
<header><h1>DocGuard / Evidence review</h1><p id="subtitle"></p></header>
<main>
<div class="bar"><button id="prev">← Previous</button><select id="select" aria-label="Select case"></select><button id="next">Next →</button><span id="progress" class="status"></span></div>
<p class="notice" id="instruction"></p>
<div class="grid"><section>
<div class="card"><h2 id="title"></h2><p class="tags" id="provenance"></p><div id="links"></div><p class="muted" id="scope"></p>
<label>Evidence shown<select id="policy"><option value="mapped">Mapped entities</option><option value="direct">Mapped entities + bounded dependencies</option></select></label>
<h3>Document supplied to the model</h3><pre id="document"></pre><details><summary>Before / after source changes</summary><pre id="changes"></pre></details>
<details open><summary>Exact evidence and identifiers</summary><div id="evidence"></div></details>
<details><summary>Missing evidence and explicit claim requirements</summary><pre id="gaps"></pre></details>
<details><summary>Upstream license and provenance</summary><pre id="license"></pre></details></div>
<div class="card" id="reference-card" hidden><h2>Engineer-authored documentation reference</h2><p id="reference-role" class="notice"></p><p class="muted">Judge meaning, factual support and preservation. Different wording can be valid; upstream edits may contain unrelated changes or mistakes.</p><details><summary>Original upstream section</summary><pre id="reference-base"></pre></details><details open><summary>Updated upstream section</summary><pre id="reference-head"></pre></details><details><summary>Upstream documentation diff</summary><pre id="reference-diff"></pre></details><details><summary>PR discussion snapshot (reviewer evidence by default)</summary><pre id="discussion"></pre></details></div>
<div class="card" id="candidate-card" hidden><h2>Candidate and final routing</h2><p id="decision"></p><pre id="candidate"></pre><details><summary>Validator findings</summary><pre id="validator"></pre></details></div>
</section><aside>
<div class="card"><h2 id="form-title"></h2><label>Your name<input id="reviewer" type="text" autocomplete="name"></label>
<label><input type="checkbox" id="independent"> Independent reviewer</label><p class="muted">Check only if you did not author the implementation, case or expected label. This is your attestation, not identity verification.</p>
<div id="fields"></div><label>Rationale and evidence references<textarea id="notes" placeholder="Quote the specific claim, cite evidence IDs/lines, and explain missing context or disagreement."></textarea></label>
<label id="reference-rating" hidden>Comparison with upstream reference<select id="reference-comparison"><option value="not_assessed">Not assessed</option><option value="consistent">Consistent in meaning</option><option value="valid_alternative">Different but valid correction</option><option value="disagrees">Substantive disagreement — explain below</option></select></label>
<p class="muted" id="review-level"></p>
<div class="buttons"><button class="primary" id="save">Save judgment</button><button id="skip">Skip for now</button></div><p id="error" role="alert"></p><p id="saved" class="status" aria-live="polite"></p></div>
<div class="card"><h2>Keep your work</h2><p class="muted">No network requests or API keys. Export JSON regularly. Browser storage is optional and may be unavailable for local files. HTML contains source evidence: share only with authorized reviewers.</p>
<button id="export">Download review JSON</button><label class="upload">Import saved JSON<input id="import" type="file" accept=".json,application/json"></label><button id="clear">Clear local draft</button></div>
<div class="card" id="metrics-card" hidden><h2>Evaluation accounting</h2><p class="muted">Method names are hidden in the rating form, not cryptographically blinded. These are decision metrics, not proof of repair correctness.</p><details><summary>Reveal methods and automatic metrics</summary><pre id="metrics"></pre></details></div>
</aside></div><footer>Review labels before running models. A case needs separate labels if expanded evidence changes what can be justified. Previously inspected pilot cases remain regression cases, even if an old manifest says held_out. Skipped judgments are not counted as approvals.</footer>
</main>
<script>
'use strict';
const bundle=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob('__BUNDLE__'),c=>c.charCodeAt(0))));
const $=id=>document.getElementById(id), report=bundle.report, outputMode=Boolean(report);
const cases=new Map(bundle.packet.cases.map(c=>[c.case,c]));
const methods=['leave_unchanged','simple_llm','docguard_mapped','docguard_direct','docguard_validated'];
const rows=outputMode?report.results.filter(r=>r.status==='completed'):bundle.packet.cases;
const key=r=>r.case+(outputMode?'::'+r.arm:'');
const hash=outputMode?bundle.report_hash:bundle.packet_hash, storage='docguard-review-v1-'+hash;
let index=0, judgments=Object.fromEntries((bundle.labels||[]).map(r=>[key(r),r]));
try{const saved=localStorage.getItem(storage);if(saved!==null)judgments=JSON.parse(saved)}catch(e){}
if(!judgments||typeof judgments!=='object'||Array.isArray(judgments))judgments={};
const criteria=outputMode?[
['supported','Are the candidate claims supported by the evidence?'],['complete','Does the candidate cover the relevant change?'],
['preserves_unrelated','Does it preserve already-correct material?'],['style_consistent','Does it preserve the document’s style?'],
['candidate_acceptable','Would you accept this candidate BEFORE the validator?'],['accepted','Do you accept the FINAL decision (including review routing)?']
]:[['mapped','Expected decision with mapped evidence'],['direct','Expected decision with expanded evidence']];
for(const [id,title] of criteria){const label=document.createElement('label');label.textContent=title;const select=document.createElement('select');select.id='field-'+id;select.append(new Option('Choose…',''));for(const [text,value] of(outputMode?[['Yes','true'],['No','false']]:[['Revise: proven stale claim with supported replacement','revise'],['Unchanged: evidence supports existing claims','unchanged'],['Needs review: relevant evidence is insufficient','needs_review']]))select.append(new Option(text,value));label.append(select);$('fields').append(label)}
$('subtitle').textContent=outputMode?'Step 2 · Rate generated decisions and candidate repairs':'Step 1 · Label pinned evidence before seeing model output';
$('instruction').textContent=outputMode?'Compare meaning against code and the upstream correction. Judge candidate quality separately from final routing. The reference is evidence, not an exact-match answer.':'Use the upstream correction to verify expected decisions before seeing model answers. You may import provisional reference labels; saving your named assessment promotes that case to project-reviewed or independently audited.';
$('form-title').textContent=outputMode?'Your repair assessment':'Your expected decisions';
$('candidate-card').hidden=!outputMode;$('metrics-card').hidden=!outputMode;
if(outputMode)$('metrics').textContent=JSON.stringify(report.metrics,null,2);
for(const [i,row] of rows.entries())$('select').append(new Option(row.case+(outputMode?' · Candidate '+String.fromCharCode(65+methods.indexOf(row.arm)):''),String(i)));
function addLink(title,url){try{const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.hostname!=='github.com')return;const a=document.createElement('a');a.textContent=title;a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';$('links').append(a)}catch(e){}}
function showEvidence(){if(!rows.length)return;const c=cases.get(rows[index].case),ctx=c.contexts[$('policy').value];$('document').textContent=ctx.document_text;$('changes').textContent=JSON.stringify(ctx.changes||[],null,2);$('gaps').textContent=JSON.stringify({gaps:ctx.evidence_gaps||[],requirements:ctx.claim_requirements||null},null,2);$('evidence').replaceChildren();for(const entry of ctx.evidence){const h=document.createElement('h3');h.textContent=entry.id+' · '+entry.path+':'+entry.start_line+'–'+entry.end_line;const pre=document.createElement('pre');pre.textContent=entry.text;$('evidence').append(h,pre)}}
function render(){
 if(!rows.length){$('title').textContent='No completed decisions to rate yet';$('save').disabled=true;return}
 const row=rows[index],c=cases.get(row.case),p=c.provenance,j=judgments[key(row)]||{};
 $('select').value=String(index);$('title').textContent=row.case;
 $('provenance').textContent=p.variant+' · '+c.exposure+'\nbase '+p.upstream_base+' → head '+p.upstream_head;
 $('scope').textContent=p.scope+' | Authored prefix: '+JSON.stringify(p.document_selections.head.authored_prefix||'none');
 const ref=c.upstream_reference;$('reference-card').hidden=!ref;
 if(ref){$('reference-base').textContent=ref.documents.base.text;$('reference-head').textContent=ref.documents.head.text;$('reference-diff').textContent=ref.diff;$('discussion').textContent=JSON.stringify(c.discussion||[],null,2);$('reference-role').textContent='Reference corrections are stored outside model contexts. Discussion mode: '+(report?.identity.discussion_mode||'withheld')+'. Updated-doc control cases already contain the updated section as their input.'}
 $('reference-rating').hidden=!outputMode||!ref;$('reference-comparison').value=j.reference_comparison||'not_assessed';
 $('review-level').textContent='Label review level: '+(outputMode?row.label_review_level:(j.review_level||(j.reviewer?(j.independent?'independently_audited':'project_reviewed'):'pending')));
 $('links').replaceChildren();addLink('Original PR',p.pr_url);addLink('Pinned code diff',p.repository_url+'/compare/'+p.upstream_base+'...'+p.upstream_head);
 const selection=p.document_selections.head;addLink('Exact upstream doc',p.repository_url+'/blob/'+selection.upstream_revision+'/'+selection.path+'#L'+selection.start_line);
 $('license').textContent=p.license_text+'\n\n'+JSON.stringify(p.document_selections,null,2);
 $('reviewer').value=j.reviewer||$('reviewer').value;$('independent').checked=j.independent===true;$('notes').value=j.notes||'';
 for(const [id] of criteria)$('field-'+id).value=j[id]===undefined?'':String(j[id]);
 $('policy').value=outputMode?row.policy:'mapped';$('policy').disabled=outputMode;
 if(outputMode){$('decision').textContent='Initial: '+(row.initial_action||row.action)+' · Final: '+row.action;$('candidate').textContent=row.candidate??c.contexts[row.policy].document_text;$('validator').textContent=JSON.stringify(row.validator_response||{note:'No validator call'},null,2)}
 $('progress').textContent=Object.keys(judgments).length+' / '+rows.length+' saved';$('saved').textContent=j.reviewer?'Saved judgment loaded':'';$('error').textContent='';$('prev').disabled=index===0;$('next').disabled=index===rows.length-1;showEvidence();
}
function persist(){try{localStorage.setItem(storage,JSON.stringify(judgments))}catch(e){$('saved').textContent+=' Browser storage unavailable; download JSON.'}}
$('save').onclick=()=>{const row=rows[index],j={case:row.case,reviewer:$('reviewer').value.trim(),independent:$('independent').checked,notes:$('notes').value.trim()};if(outputMode){j.arm=row.arm;j.reference_comparison=$('reference-comparison').value}else{j.review_level=j.independent?'independently_audited':'project_reviewed'}for(const [id]of criteria){const value=$('field-'+id).value;if(!value){$('error').textContent='Choose every judgment explicitly.';return}j[id]=outputMode?value==='true':value}if(!j.reviewer||!j.notes){$('error').textContent='Supply your name and evidence-based rationale.';return}judgments[key(row)]=j;persist();render();$('saved').textContent='Saved. Download JSON to keep a portable copy.'};
$('prev').onclick=()=>{index=Math.max(0,index-1);render()};$('next').onclick=$('skip').onclick=()=>{index=Math.min(rows.length-1,index+1);render()};$('select').onchange=()=>{index=Number($('select').value);render()};$('policy').onchange=showEvidence;
$('export').onclick=()=>{const data={schema_version:1,kind:outputMode?'docguard.experiment-reviews':'docguard.experiment-labels',[outputMode?'report_sha256':'packet_sha256']:hash,[outputMode?'reviews':'labels']:rows.map(r=>judgments[key(r)]).filter(Boolean)};const blob=new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=outputMode?'repair-reviews.json':'review-labels.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$('import').onchange=async()=>{try{const file=$('import').files[0];if(!file)return;if(file.size>1000000)throw Error('Review file too large');const data=JSON.parse(await file.text());if(data.schema_version!==1||data.kind!==(outputMode?'docguard.experiment-reviews':'docguard.experiment-labels')||data[outputMode?'report_sha256':'packet_sha256']!==hash)throw Error('This file belongs to another packet/report');const saved=data[outputMode?'reviews':'labels'];if(!Array.isArray(saved))throw Error('Invalid review array');const next={},known=new Set(rows.map(key));for(const r of saved){if(!r||!known.has(key(r))||Object.hasOwn(next,key(r)))throw Error('Unknown or duplicate case');if(typeof r.reviewer!=='string'||typeof r.notes!=='string'||typeof r.independent!=='boolean'||criteria.some(([id])=>outputMode?typeof r[id]!=='boolean':!['revise','unchanged','needs_review'].includes(r[id])))throw Error('Incomplete judgment');next[key(r)]=r}judgments=next;persist();render()}catch(e){$('error').textContent=e.message}};
$('clear').onclick=()=>{if(confirm('Clear saved judgments for this packet/report? Download a copy first.')){judgments={};persist();render()}};
render();
</script></html>"""
