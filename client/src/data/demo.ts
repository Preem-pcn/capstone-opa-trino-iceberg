/* =====================================================================
   DATA — values transcribed from the Figma stakeholder prototype (v3).
   Flight Explorer and Gold Reports read
   live data through the backend; these values feed the prototype pages only
   (static flight records, Cockpit, SQL Workspace, OPA fixtures).
   Only TG0341 / HS-THJ_20220322T111310_F01 carries verified sensor + Gold values.
   ===================================================================== */
import { utc } from '../lib/format';

export const TOTAL = 22020;                       // TG0341 recording length, s (06:07:00)
export const VERIFIED_T = 12000;                  // single repository-supported sample offset

export const FLIGHTS = [
  {no:'TG0341', id:'HS-THJ_20220322T111310_F01', date:'2022-03-22', type:'A350', tail:'HS-THJ', org:'VTBS', dst:'OPKC', dur:22020, verified:true},
  {no:'TG0648', id:'HS-TKN_20220513124029', date:'2022-05-13', type:'B777', tail:'HS-TKN', org:'VTBS', dst:'RJAA', dur:10500, chip:'Demo metadata', routeMock:true},
  {no:'TG0614', id:'HS-THE_20220826_DEMO', date:'2022-08-26', type:'A350', tail:'HS-THE', org:'VTBS', dst:'RKSI', dur:24308, chip:'Demo flight no.'},
  {no:'TG0928', id:'HS-THJ_20220921_DEMO', date:'2022-09-21', type:'A350', tail:'HS-THJ', org:'ESSA', dst:'VTBS', dur:37096, chip:'Demo flight no.'},
];

// Gold phase rows — inclusive offset boundaries
export const PH = [
  {k:'ground_out', label:'Ground Out', s:0,     e:5153,  c:'--ph-go'},
  {k:'climb',      label:'Climb',      s:5154,  e:6793,  c:'--ph-cl'},
  {k:'cruise',     label:'Cruise',     s:6794,  e:19361, c:'--ph-cr'},
  {k:'descent',    label:'Descent',    s:19362, e:21251, c:'--ph-de'},
  {k:'ground_in',  label:'Ground In',  s:21252, e:22019, c:'--ph-gi'},
];
export const EV = [
  {k:'liftoff',        label:'Liftoff',        t:5154},
  {k:'top_of_climb',   label:'Top of climb',   t:6794},
  {k:'top_of_descent', label:'Top of descent', t:19362},
  {k:'touchdown',      label:'Touchdown',      t:21251},
];
export const VERIFIED = {alt:42348, ias:244, gs:501.0, hdgRaw:-68.2031444, hdg:291.8, pitch:2.8125008, roll:0.1757813, vrtg:0.99609375};

// OPA fixtures — synthetic test rows, NOT QAR recordings
export const FIX: {flight_id:string, tail:string, origin:string, destination:string, flight_no:string, recording:string, source_file:string, hash:string|null}[] = [
  {flight_id:'HS-THJ_DEMO_01', tail:'HS-THJ', origin:'VTBS', destination:'OPKC', flight_no:'TG_DEMO_01', recording:'fixture_rec_01', source_file:'fixtures/demo_01.parquet', hash:'45c43228c3b55d0b1e756b232328e8a5bc564e6f5b4f4760d491e10c11ef75aa'},
  {flight_id:'HS-THE_DEMO_02', tail:'HS-THE', origin:'RKSI', destination:'VTBS', flight_no:'TG_DEMO_02', recording:'fixture_rec_02', source_file:'fixtures/demo_02.parquet', hash:'6b2d528fac0d1077c465889bd9b1c1d5a3f4993ddbf45eeabef9b4ef57a603db'},
  {flight_id:'HS-TKN_DEMO_03', tail:'HS-TKN', origin:'EGLL', destination:'ESSA', flight_no:'TG_DEMO_03', recording:'fixture_rec_03', source_file:'fixtures/demo_03.parquet', hash:null},
];

/* ---------- Trino/iceberg mock catalog ---------- */
export const TID = 'HS-THJ_20220322T111310_F01';
export interface Table { cols: string[]; rows: Record<string, string | number>[] }
export const TABLES: Record<string, Table> = {
  'iceberg.silver.flights': {cols:['flight_id','tail','aircraft_type','recording_start','duration_s'], rows:[
    {flight_id:TID, tail:'HS-THJ', aircraft_type:'A350', recording_start:'2022-03-22 11:13:10 UTC', duration_s:22020},
    {flight_id:'HS-THE_20220826_DEMO', tail:'HS-THE', aircraft_type:'A350', recording_start:'2022-08-26 (demo)', duration_s:24308},
    {flight_id:'HS-THJ_20220921_DEMO', tail:'HS-THJ', aircraft_type:'A350', recording_start:'2022-09-21 (demo)', duration_s:37096}]},
  'iceberg.silver.rate_0p25hz': {cols:['flight_id','ts','t_offset_s'], rows:[]},
  'iceberg.silver.rate_0p5hz':  {cols:['flight_id','ts','t_offset_s'], rows:[]},
  'iceberg.silver.rate_1hz': {cols:['flight_id','ts','t_offset_s','alt_std','ias'], rows:[
    {flight_id:TID, ts:'2022-03-22 14:33:10 UTC', t_offset_s:12000, alt_std:42348, ias:244}]},
  'iceberg.silver.rate_2hz': {cols:['flight_id','ts','t_offset_s'], rows:[]},
  'iceberg.silver.rate_4hz': {cols:['flight_id','ts','t_offset_s','gs','heading','pitch_ang_cap','rollangle_cpt'], rows:[
    {flight_id:TID, ts:'2022-03-22 14:33:10 UTC', t_offset_s:12000, gs:501.0, heading:-68.2031444, pitch_ang_cap:2.8125008, rollangle_cpt:0.1757813}]},
  'iceberg.silver.rate_7hz': {cols:['flight_id','ts','t_offset_s'], rows:[]},
  'iceberg.silver.rate_8hz': {cols:['flight_id','ts','t_offset_s','vrtg'], rows:[
    {flight_id:TID, ts:'2022-03-22 14:33:10 UTC', t_offset_s:12000, vrtg:0.99609375}]},
  'iceberg.gold.flight_summary': {cols:['flight_id','airborne_min','cruise_min','max_alt_ft','touchdown_peak_g'], rows:[
    {flight_id:TID, airborne_min:268.3, cruise_min:209.5, max_alt_ft:43036, touchdown_peak_g:1.277}]},
  'iceberg.gold.flight_phases': {cols:['flight_id','phase_order','phase','start_s','end_s','duration_s'], rows:
    PH.map((p,i)=>({flight_id:TID, phase_order:i+1, phase:p.k, start_s:p.s, end_s:p.e, duration_s:p.e-p.s+1}))},
  'iceberg.gold.flight_events': {cols:['flight_id','event','t_offset_s','ts'], rows:
    EV.map(e=>({flight_id:TID, event:e.k, t_offset_s:e.t, ts:utc(e.t)}))},
  'iceberg.opa_demo_silver.flights': {cols:['flight_id','tail','origin','destination','flight_no','recording','source_file'], rows:
    FIX.map(f=>({flight_id:f.flight_id, tail:f.tail, origin:f.origin, destination:f.destination, flight_no:f.flight_no, recording:f.recording, source_file:f.source_file}))},
  'iceberg.opa_demo_gold.flight_summary': {cols:['flight_id','flight_no','touchdown_peak_g'], rows:[
    {flight_id:'HS-THJ_DEMO_01', flight_no:'TG_DEMO_01', touchdown_peak_g:1.21},
    {flight_id:'HS-THE_DEMO_02', flight_no:'TG_DEMO_02', touchdown_peak_g:1.34},
    {flight_id:'HS-TKN_DEMO_03', flight_no:'TG_DEMO_03', touchdown_peak_g:1.18}]},
};

export const SAVED = [
  {k:'q01', name:'Verified 1 Hz sample · TG0341', sql:
`SELECT
  ts, t_offset_s, alt_std, ias
FROM iceberg.silver.rate_1hz
WHERE flight_id = '${TID}'
  AND t_offset_s BETWEEN 11990 AND 12010
ORDER BY t_offset_s
LIMIT 100;`},
  {k:'phases', name:'Gold · flight_phases', sql:
`SELECT phase_order, phase, start_s, end_s, duration_s
FROM iceberg.gold.flight_phases
WHERE flight_id = '${TID}'
ORDER BY phase_order;`},
  {k:'events', name:'Gold · flight_events', sql:
`SELECT event, t_offset_s, ts
FROM iceberg.gold.flight_events
WHERE flight_id = '${TID}'
ORDER BY t_offset_s;`},
  {k:'att', name:'4 Hz attitude & speed sample', sql:
`SELECT ts, gs, heading, pitch_ang_cap, rollangle_cpt
FROM iceberg.silver.rate_4hz
WHERE flight_id = '${TID}'
LIMIT 100;`},
  {k:'fix', name:'OPA fixtures · flights', sql:
`SELECT *
FROM iceberg.opa_demo_silver.flights;`},
  {k:'denied', name:'OPA fixtures · touchdown_peak_g', sql:
`SELECT touchdown_peak_g
FROM iceberg.opa_demo_gold.flight_summary;`},
];

export const FLIGHTS_SQL = `SELECT flight_id, tail, aircraft_type, recording_start, duration_s
FROM iceberg.silver.flights
ORDER BY recording_start;`;

/* ---------- lookups ---------- */
export type Flight = (typeof FLIGHTS)[number];
export type Phase = (typeof PH)[number];
export const flightBy = (no: string) => FLIGHTS.find(f => f.no === no);
export const phaseBy = (k: string) => PH.find(p => p.k === k);
export const phaseAt = (t: number) => PH.find(p => t >= p.s && t <= p.e + 0.999) ?? PH[PH.length - 1];
export const dur = (p: Phase) => p.e - p.s + 1;
export const savedSql = (k: string) => SAVED.find(q => q.k === k)?.sql ?? '';
