/* Silver-backed listing. The fixture SQL editor and cockpit keep their own prototype data. */
const LIVE={rows:[],loaded:false,loading:false,error:null,page:1,pageSize:20,identity:null,
  total:0,truncated:false,detail:null,detailId:null,detailLoading:false,detailError:null,request:0};
function filtered(){
  const f=S.f,q=(f.q||'').trim().toLowerCase();
  return LIVE.rows.filter(x=>(!q||[x.flight_no,x.flight_id,x.tail].some(v=>String(v||'').toLowerCase().includes(q)))&&
    (!f.from||x.flight_date>=f.from)&&(!f.to||x.flight_date<=f.to)&&
    (!f.type||x.aircraft_type===f.type)&&(!f.org||x.origin===f.org)&&(!f.dst||x.destination===f.dst)&&
    (!f.source||(f.source==='synthetic'?x.is_synthetic:!x.is_synthetic)));
}
function countText(n){return n===LIVE.rows.length?`${n} flights`:`${n} of ${LIVE.rows.length} flights`;}
function sourceBadge(f){return `<span class="pill sm ${f.is_synthetic?'':'teal'}">${f.is_synthetic?'Synthetic demo':'Recorded'}</span>`;}
function explorerRows(){
  const rows=filtered(),chip=$('#ex-count'); if(chip) chip.textContent=countText(rows.length);
  if(!LIVE.loaded&&!LIVE.error) return '<div class="state" role="status">Loading flights from Silver…</div>';
  if(LIVE.error) return `<div class="state" role="alert"><h4>Flights unavailable</h4><p>${esc(LIVE.error)}</p><button class="btn" data-act="ex-refresh">Retry</button></div>`;
  if(!rows.length) return '<div class="state"><h4>No flights match these filters</h4><p>Try a different date, aircraft, airport, or data source.</p><button class="btn" data-act="clear-filters">Reset filters</button></div>';
  const pages=Math.ceil(rows.length/LIVE.pageSize); LIVE.page=Math.min(Math.max(1,LIVE.page),pages);
  const first=(LIVE.page-1)*LIVE.pageSize,visible=rows.slice(first,first+LIVE.pageSize);
  return `<div class="scroll-x"><table class="ftable"><thead><tr><th>FLIGHT DATE</th><th>FLIGHT NO. / SOURCE</th><th>TYPE</th><th>TAIL</th><th>ROUTE</th><th>RECORDING</th><th></th></tr></thead><tbody>
    ${visible.map(f=>`<tr class="frow" data-act="live-flight" data-id="${esc(f.flight_id)}" tabindex="0">
      <td>${esc(dLong(f.flight_date))}</td><td><div class="fno" title="${esc(f.flight_id)}">${esc(f.flight_no||'—')}${sourceBadge(f)}</div></td>
      <td>${esc(f.aircraft_type||'—')}</td><td>${esc(f.tail||'—')}</td><td>${esc(f.origin||'—')} → ${esc(f.destination||'—')}</td>
      <td class="mono">${hms(f.duration_s)}</td><td><button class="btn soft" data-act="live-flight" data-id="${esc(f.flight_id)}" aria-label="Open ${esc(f.flight_no||f.flight_id)}">Open flight →</button></td></tr>`).join('')}
    </tbody></table></div><div class="ex-pagination"><span>${first+1}–${Math.min(first+LIVE.pageSize,rows.length)} of ${rows.length} matching flights</span>
    <div class="row"><button class="btn sm" data-act="ex-page" data-page="${LIVE.page-1}" ${LIVE.page===1?'disabled':''}>Previous</button>
      <span>Page ${LIVE.page} of ${pages}</span><button class="btn sm" data-act="ex-page" data-page="${LIVE.page+1}" ${LIVE.page===pages?'disabled':''}>Next</button></div></div>`;
}
function vExplorer(){
  const f=S.f,types=[...new Set(LIVE.rows.map(x=>x.aircraft_type).filter(Boolean))].sort(),orgs=[...new Set(LIVE.rows.map(x=>x.origin).filter(Boolean))].sort(),dsts=[...new Set(LIVE.rows.map(x=>x.destination).filter(Boolean))].sort();
  const recorded=LIVE.rows.filter(x=>!x.is_synthetic).length,synthetic=LIVE.rows.length-recorded;
  const sel=(id,label,value,options,all)=>`<div class="field"><label for="${id}">${label}</label><select id="${id}" class="select ${value?'set':''}"><option value="">${all}</option>${options.map(x=>`<option value="${esc(x)}" ${x===value?'selected':''}>${esc(x)}</option>`).join('')}</select></div>`;
  return `<div class="page-head"><div><h1>Browse flights</h1><p>Recorded and synthetic flights from Silver · UTC</p></div>
    <div class="row"><span class="pill" id="ex-count">${LIVE.loaded?countText(filtered().length):'Loading…'}</span><button class="btn" data-act="ex-refresh">Refresh flights</button></div></div>
    <label class="search"><span aria-hidden="true" class="muted">⌕</span><input id="f-q" type="search" placeholder="Search by flight number, flight ID, or aircraft tail" value="${esc(f.q)}" autocomplete="off"></label>
    <div class="filters"><div class="field"><label for="f-date">Flight date</label><button id="f-date" class="datebtn ${f.from||f.to?'set':''}" data-act="menu" data-menu="date" aria-haspopup="dialog">${f.from||f.to?`${esc(f.from||'…')} → ${esc(f.to||'…')}`:'All dates'}</button>
      ${S.menu==='date'?`<div class="menu datepop" role="dialog" aria-label="Flight date range"><div class="two"><div class="field"><label for="d-from">From</label><input type="date" id="d-from" value="${esc(f.from)}"></div><div class="field"><label for="d-to">To</label><input type="date" id="d-to" value="${esc(f.to)}"></div></div><div class="row" style="justify-content:flex-end"><button class="btn sm" data-act="menu-close">Cancel</button><button class="btn sm primary" data-act="date-apply">Apply</button></div></div>`:''}</div>
    ${sel('f-type','Aircraft type',f.type,types,'All types')}${sel('f-org','Origin',f.org,orgs,'All origins')}${sel('f-dst','Destination',f.dst,dsts,'All destinations')}
    <button class="btn" data-act="clear-filters" style="height:39px">Clear filters</button></div>
    <section class="card" style="padding:20px 14px 24px"><div class="card-head" style="padding:0 8px"><h3>Silver flights</h3><div class="seg2" aria-label="Data source">${[['','All',LIVE.rows.length],['recorded','Recorded',recorded],['synthetic','Synthetic',synthetic]].map(([key,label,n])=>`<button data-act="ex-source" data-source="${key}" class="${(f.source||'')===key?'on':''}" aria-pressed="${(f.source||'')===key}">${label} (${n})</button>`).join('')}</div></div>
    <div id="ex-rows">${explorerRows()}</div></section>
    <p class="small muted">Source: iceberg.silver.flights · Trino identity: ${esc(LIVE.identity||'loading')} · Flight numbers are shown as stored, including source placeholders.${LIVE.truncated?` Showing the first ${LIVE.rows.length} of ${LIVE.total} available flights.`:''}</p>`;
}
async function initFlightExplorer(force=false){
  if(LIVE.loading||(!force&&(LIVE.loaded||LIVE.error))) return;
  LIVE.loading=true; LIVE.error=null;
  if(force){LIVE.loaded=false;render();}
  try{
    const response=await fetch('/api/flights',{cache:'no-store'}),data=await response.json();
    if(!response.ok) throw new Error(data.error||'Unable to load flights.');
    LIVE.rows=data.flights;LIVE.identity=data.query_identity;LIVE.total=data.total;LIVE.truncated=data.truncated;LIVE.loaded=true;
  }catch(error){LIVE.error=error.message;}
  finally{LIVE.loading=false;if(S.page==='explorer')render();}
}
function openLiveFlight(id){S.liveFlightId=id;go('flight',{flight:id,tab:'overview'});}
async function initLiveFlight(){
  const id=S.liveFlightId;
  if(!id||S.flight!==id||(LIVE.detailId===id&&(LIVE.detailLoading||LIVE.detail||LIVE.detailError)))return;
  const request=++LIVE.request;LIVE.detailId=id;LIVE.detail=null;LIVE.detailError=null;LIVE.detailLoading=true;
  try{
    const response=await fetch('/api/flights/detail?id='+encodeURIComponent(id),{cache:'no-store'}),data=await response.json();
    if(!response.ok)throw new Error(data.error||'Unable to load flight details.');
    if(request===LIVE.request)LIVE.detail=data;
  }catch(error){if(request===LIVE.request)LIVE.detailError=error.message;}
  finally{if(request===LIVE.request){LIVE.detailLoading=false;if(S.page==='flight'&&S.flight===id)render();}}
}
function liveFlightCrumbs(){
  const f=LIVE.detailId===S.liveFlightId&&LIVE.detail?LIVE.detail.flight:null;
  return `<button data-act="nav" data-page="explorer">Flights</button><span class="sep">/</span><span>${esc(f?(f.flight_no||f.flight_id):'Flight details')}</span>`;
}
function vLiveFlight(){
  const back='<button class="btn" data-act="nav" data-page="explorer">← Back to flights</button>';
  if(LIVE.detailId!==S.liveFlightId||LIVE.detailLoading||(!LIVE.detail&&!LIVE.detailError))return back+'<section class="card" role="status">Loading this flight from Silver and Gold…</section>';
  if(LIVE.detailError)return back+`<section class="card" role="alert">${esc(LIVE.detailError)}</section>`;
  const {flight:f,summary:g,phases,events}=LIVE.detail;
  const val=(x,digits=1)=>x===null||x===undefined?'—':Number(x).toLocaleString('en-US',{maximumFractionDigits:digits});
  const table=(headers,rows)=>`<div class="scroll-x"><table class="dtable"><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${esc(x??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  let html=`<div class="page-head"><div><div class="eyebrow">FLIGHT RECORD / ${esc(f.aircraft_type)}</div><h1>${esc(f.flight_no||f.flight_id)}</h1><p>${esc(f.tail)} · ${esc(f.origin)} → ${esc(f.destination)} · ${esc(dLong(f.flight_date))}</p></div><div class="row">${sourceBadge(f)}${back}</div></div>
    <div class="tabs" role="tablist">${[['overview','Overview'],['phases','Phases & Events']].map(([key,label])=>`<button class="tab ${S.tab===key?'on':''}" role="tab" aria-selected="${S.tab===key}" data-act="tab" data-tab="${key}">${label}</button>`).join('')}</div>`;
  if(S.tab==='phases')return html+`<section class="card"><div class="card-head"><h3>Flight phases</h3><span class="note">Inclusive recording offsets</span></div>${table(['Phase','Start (s)','End (s)','Duration','Detector'],phases.map(p=>[p.phase,p.start_s,p.end_s,hms(p.duration_s),p.detector_ver]))}</section><section class="card"><div class="card-head"><h3>Detected events</h3></div>${table(['Event','Offset (s)','UTC time','Value','Unit'],events.map(e=>[e.event,e.t_offset_s,e.ts,val(e.value,3),e.unit]))}</section>`;
  html+=g?`<div class="grid-4">${metric('Airborne time',val(g.airborne_min),'min','Gold summary')}${metric('Cruise time',val(g.cruise_min),'min','Gold summary')}${metric('Maximum altitude',val(g.max_alt_ft,0),'ft','Pressure altitude')}${metric('Touchdown peak',val(g.touchdown_peak_g,3),'g','Gold event value')}</div>`:'<section class="card">Gold summary is not available for this flight yet.</section>';
  return html+`<section class="card"><div class="card-head"><h3>Recording details</h3><span class="note">Trino identity: ${esc(LIVE.detail.query_identity)}</span></div><dl class="kv"><dt>Flight ID</dt><dd>${esc(f.flight_id)}</dd><dt>Data source</dt><dd>${f.is_synthetic?'Synthetic demo':'Decoded recording'}</dd><dt>Recording start (UTC)</dt><dd>${esc(f.start_time)}</dd><dt>Recording duration</dt><dd>${hms(f.duration_s)}</dd><dt>Recording</dt><dd>${esc(f.recording)}</dd><dt>Decoder version</dt><dd>${esc(f.decoder_version)}</dd></dl></section>`;
}
