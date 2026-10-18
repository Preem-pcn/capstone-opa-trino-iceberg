"""Build a Metabase-connected copy of the supplied v3 prototype; retain source."""

import hashlib
from pathlib import Path
from bi_demo_settings import get_query_identity

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bi/web/qar-flight-analytics_3.html"
OUTPUT = SOURCE.with_name("qar-flight-analytics-capstone-metabase.html")

GOLD = r'''
/* Gold reports use the live, signed Metabase dashboard. Other pages retain v3 behavior. */
let goldRefreshTimer = null;
function vGold(){
  return `
  <div class="page-head">
    <div><h1>Gold Reports</h1><p>Existing Iceberg Gold data · queried through Trino and visualized by Metabase</p></div>
    <div class="row"><button class="btn" data-act="bi-refresh">Refresh dashboard</button>
      <button class="btn primary" data-act="metabase">Open in Metabase ↗</button></div>
  </div>
  <section class="card bi-context">
    <div class="row" style="justify-content:space-between"><b>Metabase · Live Gold dashboard · capstone-opa-trino-iceberg</b>
      <span class="pill teal">Trino identity: safety_analyst · read-only</span></div>
    <p class="small muted" style="margin-top:9px">Use Flight date and Aircraft type inside the dashboard. Source: capstone-opa-trino-iceberg · Trino localhost:8083. These charts read this repo’s Gold tables; the other prototype pages keep their sample data. Demo identity changes apply to OPA fixtures, not this shared BI connection.</p>
  </section>
  <section class="card bi-dashboard">
    <div id="bi-load-state" role="status" class="bi-load-state">Connecting to Metabase…</div>
    <iframe id="gold-metabase-frame" title="Metabase dashboard showing actual QAR Gold data" hidden></iframe>
  </section>`;
}
async function initGoldEmbed(){
  clearTimeout(goldRefreshTimer);
  const frame=document.getElementById('gold-metabase-frame');
  const state=document.getElementById('bi-load-state');
  if(!frame||!state) return;
  state.hidden=false; state.textContent='Connecting to Metabase…';
  try {
    const response=await fetch('/api/bi/embed', {cache:'no-store'});
    const info=await response.json();
    if(!response.ok) throw new Error(info.error||'Metabase is not ready.');
    if(!frame.isConnected) return;
    frame.onload=()=>{ if(state.isConnected) state.hidden=true; };
    frame.src=info.embed_url; frame.hidden=false;
    state.textContent='Loading the Gold dashboard…';
    goldRefreshTimer=setTimeout(()=>{if(S.page==='gold') initGoldEmbed();}, info.refresh_after_seconds*1000);
  } catch(error){
    if(state.isConnected) state.textContent='Dashboard unavailable. Start the local BI demo server and Metabase, then use Refresh dashboard.';
  }
}
'''

def build():
    identity = get_query_identity()
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("/* =====================================================================\n   PAGE: GOLD REPORTS")
    end = text.index("/* =====================================================================\n   PAGE: SITE MAP", start)
    gold = GOLD.replace("safety_analyst", identity)
    if identity == "admin":
        gold = gold.replace("admin · read-only", "admin · demo")
    text = text[:start] + gold + "\n" + text[end:]
    explorer_start = text.index("/* =====================================================================\n   PAGE: FLIGHT EXPLORER")
    explorer_end = text.index("/* =====================================================================\n   PAGE: FLIGHT DETAIL", explorer_start)
    text = text[:explorer_start] + (ROOT / "bi/web/flight-explorer.js").read_text(encoding="utf-8") + "\n" + text[explorer_end:]
    text = text.replace("function vFlight(){", "function vFlight(){\n  if(S.liveFlightId && S.flight===S.liveFlightId) return vLiveFlight();", 1)
    text = text.replace("function crumbs(){", "function crumbs(){\n  if(S.page==='flight' && S.liveFlightId && S.flight===S.liveFlightId) return liveFlightCrumbs();", 1)
    text = text.replace("  f:{q:'', from:'2022-01-01', to:'2022-12-31', type:'', org:'', dst:''},", "  f:{q:'', from:'', to:'', type:'', org:'', dst:'', source:''},", 1)
    anchor = "function render(){\n  renderSide(); renderTop();"
    if text.count(anchor) != 1:
        raise ValueError("Source render structure changed; review before rebuilding.")
    text = text.replace(anchor, "function render(){\n  clearTimeout(goldRefreshTimer);\n  renderSide(); renderTop();")
    text = text.replace("  if(S.page==='sql') setupEditor();", "  if(S.page==='gold') initGoldEmbed();\n  if(S.page==='sql') setupEditor();", 1)
    text = text.replace("  if(S.page==='sql') setupEditor();", "  if(S.page==='explorer') initFlightExplorer();\n  if(S.page==='flight' && S.liveFlightId && S.flight===S.liveFlightId) initLiveFlight();\n  if(S.page==='sql') setupEditor();", 1)
    text = text.replace("    case 'open-flight':", """    case 'live-flight': e.stopPropagation(); openLiveFlight(d.id); break;
    case 'ex-refresh': initFlightExplorer(true); break;
    case 'ex-source': S.f.source=d.source; LIVE.page=1; render(); break;
    case 'ex-page': LIVE.page=+d.page; $('#ex-rows').innerHTML=explorerRows(); break;
    case 'open-flight':""", 1)
    text = text.replace("S.f={q:'',from:'2022-01-01',to:'2022-12-31',type:'',org:'',dst:''};", "S.f={q:'',from:'',to:'',type:'',org:'',dst:'',source:''}; LIVE.page=1;", 1)
    text = text.replace("S.f.from=f; S.f.to=t;", "S.f.from=f; S.f.to=t; LIVE.page=1;", 1)
    text = text.replace("S.f.q=t.value;", "S.f.q=t.value; LIVE.page=1;", 1)
    text = text.replace("S.f[map[t.id]]=t.value;", "S.f[map[t.id]]=t.value; LIVE.page=1;", 1)
    original_action = "case 'metabase': toast('Metabase handoff is proposed · not connected in this prototype.'); break;"
    if text.count(original_action) != 1:
        raise ValueError("Source Metabase action changed; review before rebuilding.")
    text = text.replace(original_action, "case 'metabase': window.open('/metabase', '_blank', 'noopener'); break;\n    case 'bi-refresh': initGoldEmbed(); break;")
    gold_map_start = text.index("    ['Gold Reports','--st4','gold',[")
    gold_map_end = text.index("    ['Prototype'", gold_map_start)
    text = text[:gold_map_start] + """    ['Gold Reports','--st4','gold',[
      ['Metabase dashboard','content',null,null,'live Gold through Trino · shared safety_analyst connection'],
      ['Filters and KPIs','content',null,null,'flight date · aircraft type · count · time · altitude'],
      ['Charts and tables','content',null,null,'route · phases · flight summary · events'],
    ]],
""".replace("safety_analyst", identity) + text[gold_map_end:]
    text = text.replace("Metabase handoff and dashboard filters are proposed; only one verified Gold flight represented.",
                        f"Flight Explorer reads Silver through Trino. Gold Reports embeds a live Metabase dashboard using the shared capstone Trino {identity} connection. Cockpit and SQL Workspace retain prototype data.")
    text = text.replace("These charts read this repo’s Gold tables; the other prototype pages keep their sample data.", "These charts read this repo’s Gold tables. Flight Explorer reads Silver; Cockpit and SQL Workspace keep their prototype data.")
    text = text.replace("Gold Reports → Flights table → <b>Flight Detail</b>",
                        "Gold Reports → <b>Metabase dashboard</b> (live Gold; cross-page drill-through is not configured)")
    text = text.replace("</style>", """\n/* Live Metabase panel */
.bi-dashboard{padding:8px;overflow:hidden}
.bi-dashboard iframe{display:block;width:100%;height:1560px;border:0;background:white;border-radius:6px}
.bi-dashboard iframe[hidden]{display:none}
.bi-load-state{padding:24px;color:var(--ink-2)}
.ex-pagination{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;padding:18px 10px 0;font-size:12px;color:var(--ink-2)}
.kv dd{overflow-wrap:anywhere}
</style>""", 1)
    if '<meta charset=' not in text.lower():
        text = '<meta charset="utf-8">\n' + text
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    text = '<!-- Generated from qar-flight-analytics_3.html; source SHA256 ' + digest + ' -->\n' + text
    OUTPUT.write_text(text, encoding="utf-8")
    print("Built:", OUTPUT)
    print("Source retained:", SOURCE)


if __name__ == "__main__":
    build()
