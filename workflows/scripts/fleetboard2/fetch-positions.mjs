#!/usr/bin/env node
/**
 * Fleetboard 2.0 — GPS-Positionen abrufen
 *
 * Ruft die aktuelle Position ALLER Fahrzeuge ueber die Fleetboard SOAP API ab
 * und speichert sie in Supabase (fleetboard_positions).
 *
 * Ablauf: Login -> getLastPosition -> Kennzeichen zuordnen -> Supabase INSERT
 * Laeuft jede Minute via Cron/Scheduler.
 *
 * Usage:
 *   node fetch-positions.mjs
 */

import { sb } from './lib.mjs';

// --- Fleetboard SOAP Config (aus Env) ---
const FB_URL  = process.env.FLEETBOARD_SOAP_URL || 'https://soap.api.fleetboard.com/soap_v1_1/services';
const FB_FLEET = process.env.FLEETBOARD_FLEET_NAME || 'GVTrucknet';
const FB_USER  = process.env.FLEETBOARD_USER || 'UIXUIX';
const FB_PASS  = process.env.FLEETBOARD_PASSWORD;
const FB_BASIC = '/BasicService';
const FB_POS   = '/PosService';

if (!FB_PASS) {
  console.error('FLEETBOARD_PASSWORD muss gesetzt sein');
  process.exit(1);
}

// --- SOAP Helper ---
async function soapRequest(url, action, body) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': `"${action}"` },
    body
  });
  if (!resp.ok) {
    const errText = await resp.text().catch(() => '');
    throw new Error(`SOAP ${action}: HTTP ${resp.status} — ${errText.substring(0, 800)}`);
  }
  return resp.text();
}

// --- Login -> SessionID ---
async function login() {
  const body = '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tp="http://www.fleetboard.com/data"><soapenv:Body><tp:login><tp:LoginRequest><tp:Fleetname>' + FB_FLEET + '</tp:Fleetname><tp:User>' + FB_USER + '</tp:User><tp:Password>' + FB_PASS + '</tp:Password></tp:LoginRequest></tp:login></soapenv:Body></soapenv:Envelope>';
  const xml = await soapRequest(FB_URL + FB_BASIC, 'login', body);
  const m = xml.match(/sessionid="([^"]+)"/i) || xml.match(/sessionid>([^<]+)</i);
  if (!m) throw new Error('Login fehlgeschlagen — keine SessionID in Response');
  return m[1];
}

// --- Letzte Positionen aller Fahrzeuge ---
async function getLastPositions(sessionId) {
  const body = '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tp="http://www.fleetboard.com/data"><soapenv:Body><tp:getLastPosition><tp:GetLastPositionRequest sessionid="' + sessionId + '"><tp:QueryType>1</tp:QueryType></tp:GetLastPositionRequest></tp:getLastPosition></soapenv:Body></soapenv:Envelope>';
  const xml = await soapRequest(FB_URL + FB_POS, 'getLastPosition', body);
  const positions = [];
  const blocks = xml.matchAll(/(?:Positions>)([\s\S]*?)(?:\/\w*:?Positions>)/g);
  for (const block of blocks) {
    const c = block[1];
    const vid = c.match(/VehicleID>(\d+)</)?.[1];
    const ts  = c.match(/Position\s+timestamp="([^"]+)"/)?.[1];
    const lat = c.match(/Lat>([\d.\-]+)</)?.[1];
    const lon = c.match(/Long>([\d.\-]+)</)?.[1];
    if (vid && lat && lon) {
      positions.push({ vehicleId: vid, timestamp: ts, lat: parseFloat(lat), lon: parseFloat(lon) });
    }
  }
  return positions;
}

// --- Kennzeichen zu VehicleID abfragen ---
async function getRegistration(sessionId, vehicleId) {
  const body = '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tp="http://www.fleetboard.com/data"><soapenv:Body><tp:getVehicle><tp:GetVehicleRequest sessionid="' + sessionId + '"><tp:VehicleID>' + vehicleId + '</tp:VehicleID></tp:GetVehicleRequest></tp:getVehicle></soapenv:Body></soapenv:Envelope>';
  const xml = await soapRequest(FB_URL + FB_BASIC, 'getVehicle', body);
  const m = xml.match(/REGISTRATION>([^<]+)</);
  return m ? m[1].replace(/[\s\-]/g, '').toUpperCase() : null;
}

// --- Kennzeichen-Cache (Supabase) ---
async function loadKennzeichenCache() {
  const { data } = await sb.from('fleetboard_vehicles').select('vehicle_id, kennzeichen');
  const map = {};
  for (const v of (data || [])) map[v.vehicle_id] = v.kennzeichen;
  return map;
}

async function saveKennzeichen(vehicleId, kennzeichen) {
  await sb.from('fleetboard_vehicles').upsert({
    vehicle_id: vehicleId, kennzeichen, updated_at: new Date().toISOString()
  }, { onConflict: 'vehicle_id' });
}

// --- Positionen in Supabase speichern ---
async function storePositions(records) {
  if (!records.length) return 0;
  const { error } = await sb.from('fleetboard_positions').insert(records);
  if (error) throw new Error('Insert fehlgeschlagen: ' + error.message);
  return records.length;
}

// --- Main ---
async function main() {
  const t0 = Date.now();
  console.log('=== Fleetboard 2.0 — GPS Fetch ===\n');
  const sessionId = await login();
  console.log('Login OK');
  const positions = await getLastPositions(sessionId);
  console.log(`${positions.length} Fahrzeuge mit Position`);
  if (!positions.length) { console.log('Keine Positionen — fertig.'); return; }
  const kzCache = await loadKennzeichenCache();
  const records = [];
  for (const pos of positions) {
    let kz = kzCache[pos.vehicleId];
    if (!kz) {
      try {
        kz = await getRegistration(sessionId, pos.vehicleId);
        if (kz) { kzCache[pos.vehicleId] = kz; await saveKennzeichen(pos.vehicleId, kz); console.log(`  Neues Fahrzeug: ${pos.vehicleId} -> ${kz}`); }
      } catch (e) { console.warn(`  Fahrzeug ${pos.vehicleId}: ${e.message.substring(0, 100)}`); }
    }
    records.push({ vehicle_id: pos.vehicleId, kennzeichen: kz || 'UNBEKANNT', lat: pos.lat, lon: pos.lon, gps_time: pos.timestamp || new Date().toISOString(), fetched_at: new Date().toISOString() });
  }
  const count = await storePositions(records);
  const ms = Date.now() - t0;
  console.log(`\n${count} Positionen gespeichert (${ms}ms)`);
  await sb.from('workflow_runs').insert({ workflow_id: 'fleetboard2/gps-fetch', status: 'success', vm: process.env.COMPUTERNAME || 'unknown', started_at: new Date(t0).toISOString(), finished_at: new Date().toISOString(), metrics: { vehicles: count, duration_ms: ms }, agent_id: 'fleetboard2-agent', trigger: 'scheduled-task' });
  console.log('Done.');
}

main().catch(e => {
  console.error('FATAL:', e.message);
  sb.from('workflow_runs').insert({ workflow_id: 'fleetboard2/gps-fetch', status: 'error', vm: process.env.COMPUTERNAME || 'unknown', started_at: new Date().toISOString(), finished_at: new Date().toISOString(), error_message: e.message, agent_id: 'fleetboard2-agent', trigger: 'scheduled-task' }).then(() => process.exit(1));
});
