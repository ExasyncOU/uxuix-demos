#!/usr/bin/env node
/**
 * Fleetboard 2.0 — Tour-Matcher
 *
 * Matcht GPS-Traces aus Supabase gegen AUSSTEHEND-Eintraege in fleetboard_arrivals.
 * Fuer jeden Stopp wird geprueft ob ein Trace in der Bounding Box
 * oder innerhalb des Distanz-Fallback liegt.
 *
 * Primaere Quelle: DB (fleetboard_arrivals WHERE status = 'AUSSTEHEND')
 * Optional: CSV-Import neuer Touren mit --import flag
 *
 * Usage:
 *   node match-tours.mjs                     # Matcht AUSSTEHEND aus DB
 *   node match-tours.mjs --import tour.csv   # Importiert CSV, dann matcht
 */

import { readFileSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { sb, loadCache, CACHE_DIR } from './lib.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));

const DISTANCE_THRESHOLD_KM = 15;

// Kennzeichen normalisieren: "HEF IZ 290" -> "HEFIZ290"
const normKz = kz => kz.replace(/[\s\-]/g, '').toUpperCase();

// --- CSV parsen ---
function parseTours(csvPath) {
  const raw = readFileSync(csvPath, 'latin1');
  const lines = raw.split('\n').filter(l => l.trim());
  const headers = lines[0].replace(/;$/, '').split(';').map(h => h.trim().replace(/"/g, ''));

  const col = name => headers.findIndex(h => h === name);
  const idx = {
    aufNr: col('AufNr'), tourNr: col('TourNr'), kz: col('KfzPolKz'),
    belDat: col('BelDat'), belVonDat: col('BelVonDat'), belVonZeit: col('BelVonZeit'),
    entVonDat: col('EntVonDat'), entVonZeit: col('EntVonZeit'),
    entBisDat: col('EntBisDat'), entBisZeit: col('EntBisZeit'),
    tourBez: col('TourBez'), zref: col('Zustellreferenz'),
    emgOrt: col('EmgOrt')
  };

  const stops = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].replace(/;$/, '').split(';').map(s => s.trim().replace(/"/g, ''));
    const zref = c[idx.zref];
    if (!zref) continue;

    stops.push({
      aufNr: c[idx.aufNr],
      tourNr: c[idx.tourNr],
      kennzeichen: c[idx.kz],
      tourBez: c[idx.tourBez],
      zustellreferenz: zref,
      ort: c[idx.emgOrt],
      belDat: c[idx.belDat]?.split(' ')[0] || null,
      sollAnkunft: combineDateTime(c[idx.entVonDat], c[idx.entVonZeit]),
      sollAbfahrt: combineDateTime(c[idx.entBisDat], c[idx.entBisZeit]),
      belVon: combineDateTime(c[idx.belVonDat], c[idx.belVonZeit])
    });
  }
  return stops;
}

// --- Datum+Zeit kombinieren (GV-Format: "13.03.2026 00:00:00" + "30.12.1899 04:30:00") ---
function combineDateTime(datePart, timePart) {
  if (!datePart || !timePart) return null;
  const d = datePart.split(' ')[0]; // "13.03.2026"
  const t = timePart.split(' ')[1] || timePart.split(' ')[0]; // "04:30:00"
  const [day, month, year] = d.split('.');
  return new Date(`${year}-${month}-${day}T${t}`);
}

// --- Haversine-Distanz in km ---
function distanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// --- Trace gegen Area pruefen ---
function traceInArea(trace, area) {
  const hasBox = area.lat_min != null && area.lat_max != null && area.lon_min != null && area.lon_max != null;
  if (hasBox && trace.lat >= area.lat_min && trace.lat <= area.lat_max &&
      trace.lon >= area.lon_min && trace.lon <= area.lon_max) {
    return { match: true, method: 'BBOX', distance_km: 0 };
  }
  const latMin = area.lat_min ?? area.lat_max;
  const latMax = area.lat_max ?? area.lat_min;
  const lonMin = area.lon_min ?? area.lon_max;
  const lonMax = area.lon_max ?? area.lon_min;
  if (latMin == null || lonMin == null) return { match: false, distance_km: 999 };
  const centerLat = (latMin + latMax) / 2;
  const centerLon = (lonMin + lonMax) / 2;
  const dist = distanceKm(trace.lat, trace.lon, centerLat, centerLon);
  if (dist <= DISTANCE_THRESHOLD_KM) {
    return { match: true, method: 'DISTANZ', distance_km: Math.round(dist * 10) / 10 };
  }
  return { match: false, distance_km: Math.round(dist * 10) / 10 };
}

// --- Besten Trace in Area finden ---
const MAX_MATCH_DELTA_MS = 8 * 60 * 60 * 1000; // 8h max Abweichung zur Sollzeit
function findBestTrace(traces, area, minTime, { mode = 'earliest', targetTime } = {}, usedTraces = null) {
  let best = null;
  let bestDelta = Infinity;
  for (const trace of traces) {
    const traceTime = new Date(trace.gps_time);
    if (minTime && traceTime < minTime) continue;
    if (usedTraces && usedTraces.has(`${trace.kennzeichen}@${trace.gps_time}`)) continue;
    const check = traceInArea(trace, area);
    if (check.match) {
      if (mode === 'closest' && targetTime) {
        const delta = Math.abs(traceTime - targetTime);
        if (delta < bestDelta && delta <= MAX_MATCH_DELTA_MS) { bestDelta = delta; best = { ...trace, ...check }; }
      } else {
        if (!best || traceTime < new Date(best.gps_time)) { best = { ...trace, ...check }; }
      }
    }
  }
  return best;
}

// --- Neueste CSV automatisch finden ---
function findLatestCsv(dir) {
  const candidates = [dir, CACHE_DIR, join(__dirname, 'cache')];
  if (process.platform === 'win32') candidates.push('C:\\FleetboardScript');
  for (const csvDir of candidates) {
    if (!csvDir) continue;
    try {
      const files = readdirSync(csvDir)
        .filter(f => /^Tourenabfrage.*\.csv$/i.test(f))
        .sort()
        .reverse();
      if (files.length) return join(csvDir, files[0]);
    } catch { /* dir not found, try next */ }
  }
  return null;
}

// --- AUSSTEHEND-Stopps aus DB laden ---
async function loadPendingFromDb(cache) {
  // Zeitfenster: soll_ankunft in den letzten 36h (deckt Nachttouren ab)
  const since = new Date();
  since.setHours(since.getHours() - 36);

  const { data, error } = await sb.from('fleetboard_arrivals')
    .select('tour_nr, tour_bez, kennzeichen, zustellreferenz, zielgebiet, tourdatum, soll_ankunft, beladung')
    .eq('status', 'AUSSTEHEND')
    .gte('soll_ankunft', since.toISOString())
    .order('soll_ankunft');

  if (error) throw new Error('DB-Abfrage fehlgeschlagen: ' + error.message);
  if (!data || !data.length) return { matchable: [], unknown: [] };

  const matchable = [];
  const unknown = [];
  for (const row of data) {
    const stop = {
      aufNr: null,
      tourNr: row.tour_nr,
      kennzeichen: row.kennzeichen,
      tourBez: row.tour_bez,
      zustellreferenz: row.zustellreferenz,
      ort: row.zielgebiet,
      belDat: row.tourdatum,
      sollAnkunft: row.soll_ankunft ? new Date(row.soll_ankunft) : null,
      sollAbfahrt: null,
      belVon: row.beladung ? new Date(row.beladung) : null
    };
    if (cache.refLookup[stop.zustellreferenz]) {
      matchable.push(stop);
    } else if (stop.zustellreferenz) {
      unknown.push(stop);
    }
  }
  return { matchable, unknown };
}

// --- CSV importieren: neue Touren als AUSSTEHEND in DB schreiben ---
async function importCsvToDb(csvPath, cache) {
  const stops = parseTours(csvPath);
  console.log(`CSV-Import: ${csvPath} — ${stops.length} Stopps`);

  const rows = stops.filter(s => cache.refLookup[s.zustellreferenz]).map(s => ({
    tour_nr: s.tourNr,
    tour_bez: s.tourBez,
    kennzeichen: normKz(s.kennzeichen),
    zustellreferenz: s.zustellreferenz,
    zielgebiet: s.ort,
    beladung: s.belVon?.toISOString() || null,
    soll_ankunft: s.sollAnkunft?.toISOString() || null,
    ist_ankunft: null,
    status: 'AUSSTEHEND',
    entfernung_km: null,
    geo_match: 'NEIN',
    tourdatum: s.belDat,
    typ: 'ZUSTELLUNG'
  }));

  if (!rows.length) { console.log('Keine matchbaren Stopps in CSV.'); return 0; }

  const { error } = await sb.from('fleetboard_arrivals')
    .upsert(rows, { onConflict: 'tour_nr,zustellreferenz,soll_ankunft', ignoreDuplicates: true });
  if (error) {
    console.error('CSV-Import Fehler:', error.message);
    return 0;
  }
  console.log(`${rows.length} Stopps importiert/aktualisiert.\n`);
  return rows.length;
}

// --- Main ---
async function main() {
  const args = process.argv.slice(2);
  const importFlag = args.indexOf('--import');
  let csvPath = null;

  // --import tour.csv: CSV importieren
  if (importFlag >= 0 && args[importFlag + 1]) {
    csvPath = args[importFlag + 1];
  }
  // Legacy: direktes CSV-Argument ohne Flag -> als Import behandeln
  if (!csvPath && args[0] && !args[0].startsWith('--')) {
    csvPath = args[0];
  }

  console.log('=== Fleetboard 2.0 — Tour-Matcher ===\n');

  // Geodaten-Cache laden
  const cache = loadCache();
  if (!cache) { console.error('Kein Geodaten-Cache. Erst: node sync-geodata.mjs'); process.exit(1); }
  console.log(`Cache: ${Object.keys(cache.refLookup).length} Zustellreferenzen`);

  // CSV-Import falls angegeben
  if (csvPath) {
    await importCsvToDb(csvPath, cache);
  }

  // AUSSTEHEND-Stopps aus DB laden (PRIMAERE QUELLE)
  const { matchable, unknown } = await loadPendingFromDb(cache);
  console.log(`DB: ${matchable.length} ausstehende Stopps, ${unknown.length} unbekannte Refs`);

  if (!matchable.length) {
    console.log('Keine ausstehenden Stopps — nichts zu matchen.\n');
  }

  // Alle Kennzeichen sammeln (normalisiert fuer DB-Abfrage)
  const platesRaw = [...new Set(matchable.map(s => s.kennzeichen))];
  const platesNorm = [...new Set(platesRaw.map(normKz))];
  console.log(`Fahrzeuge: ${platesRaw.join(', ')}\n`);

  // GPS-Positionen laden: gestern 12:00 bis jetzt (Nachttouren starten abends)
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  yesterday.setHours(12, 0, 0, 0);
  const gpsFrom = yesterday.toISOString();
  const gpsTo = now.toISOString();
  const tracesByPlate = {};
  let totalTraces = 0;

  // Alle Fahrzeuge mit Daten laden (fuer Begegnungsverkehr-Fallback)
  const { data: vehicleRows } = await sb.from('fleetboard_vehicles')
    .select('kennzeichen');
  const allPlates = vehicleRows?.map(r => r.kennzeichen) || platesNorm;
  console.log(`Lade GPS fuer ${allPlates.length} Fahrzeuge (${gpsFrom.substring(0,16)} bis jetzt)...`);

  for (const plate of allPlates) {
    if (tracesByPlate[plate]) continue;
    let allData = [];
    let offset = 0;
    const PAGE = 1000;
    while (true) {
      const { data: page, error: pageErr } = await sb.from('fleetboard_positions')
        .select('kennzeichen, lat, lon, gps_time')
        .eq('kennzeichen', plate)
        .gte('gps_time', gpsFrom)
        .lte('gps_time', gpsTo)
        .order('gps_time')
        .range(offset, offset + PAGE - 1);
      if (pageErr || !page || page.length === 0) break;
      allData = allData.concat(page);
      if (page.length < PAGE) break;
      offset += PAGE;
    }
    tracesByPlate[plate] = allData;
    totalTraces += allData.length;
  }
  const allLoadedPlates = Object.keys(tracesByPlate);
  console.log(`Positionen geladen: ${totalTraces} Punkte fuer ${allLoadedPlates.length} Fahrzeuge\n`);

  // Matching (mit Begegnungsverkehr-Fallback)
  const usedTraces = new Set();
  const traceKey = (kz, time) => `${kz}@${time}`;

  const results = [];
  for (const stop of matchable) {
    const area = cache.refLookup[stop.zustellreferenz];
    const plannedPlate = normKz(stop.kennzeichen);

    const isDepot = stop.zustellreferenz === 'GVLOGMG';
    const matchOpts = { mode: 'closest', targetTime: stop.sollAnkunft };

    let depotMinTime = null;
    if (isDepot) {
      const tourResults = results.filter(r => r.tourNr === stop.tourNr && r.zustellreferenz !== 'GVLOGMG' && r.istAnkunft);
      if (tourResults.length > 0) {
        const lastDelivery = tourResults.reduce((a, b) => new Date(a.istAnkunft) > new Date(b.istAnkunft) ? a : b);
        depotMinTime = new Date(lastDelivery.istAnkunft);
      }
    }

    let bestMatch = findBestTrace(tracesByPlate[plannedPlate] || [], area, isDepot ? depotMinTime : stop.belVon, matchOpts, usedTraces);

    // Begegnungsverkehr-Fallback (nicht fuer GVLOGMG)
    if (!bestMatch && !isDepot) {
      for (const plate of allLoadedPlates) {
        if (plate === plannedPlate) continue;
        const hit = findBestTrace(tracesByPlate[plate] || [], area, stop.belVon, matchOpts, usedTraces);
        if (hit && (!bestMatch || Math.abs(new Date(hit.gps_time) - stop.sollAnkunft) < Math.abs(new Date(bestMatch.gps_time) - stop.sollAnkunft))) {
          bestMatch = hit;
        }
      }
    }

    if (bestMatch) usedTraces.add(traceKey(bestMatch.kennzeichen, bestMatch.gps_time));

    const isSwap = bestMatch && bestMatch.kennzeichen !== plannedPlate;
    results.push({
      aufNr: stop.aufNr,
      tourNr: stop.tourNr,
      kennzeichen: stop.kennzeichen,
      actualKennzeichen: bestMatch?.kennzeichen || null,
      tourBez: stop.tourBez,
      zustellreferenz: stop.zustellreferenz,
      ort: stop.ort,
      tourdatum: stop.belDat,
      belVon: stop.belVon?.toISOString() || null,
      sollAnkunft: stop.sollAnkunft?.toISOString() || null,
      istAnkunft: bestMatch ? bestMatch.gps_time : null,
      status: bestMatch ? 'MATCHED' : 'AUSSTEHEND',
      matchMethod: bestMatch?.method || null,
      distanceKm: bestMatch?.distance_km ?? null,
      begegnungsverkehr: isSwap
    });
  }

  // Ergebnis ausgeben
  console.log('--- Ergebnisse ---\n');
  const matched = results.filter(r => r.status === 'MATCHED');
  const pending = results.filter(r => r.status === 'AUSSTEHEND');

  for (const r of results) {
    const icon = r.status === 'MATCHED' ? (r.begegnungsverkehr ? '[BV]' : '[OK]') : '[--]';
    const detail = r.istAnkunft
      ? `ist=${r.istAnkunft} (${r.matchMethod}, ${r.distanceKm}km)${r.begegnungsverkehr ? ' via ' + r.actualKennzeichen : ''}`
      : 'kein Trace im Gebiet';
    console.log(`${icon} ${r.kennzeichen} ${r.zustellreferenz} -> ${detail}`);
  }

  const bvCount = results.filter(r => r.begegnungsverkehr).length;
  console.log(`\n${matched.length}/${results.length} gematcht (${bvCount} Begegnungsverkehr), ${pending.length} ausstehend, ${unknown.length} unbekannte Refs`);

  // In Supabase schreiben — nur gematchte Eintraege updaten
  const matchedResults = results.filter(r => r.status === 'MATCHED');
  const rows = matchedResults.map(r => ({
    tour_nr: r.tourNr,
    tour_bez: r.tourBez,
    kennzeichen: normKz(r.kennzeichen),
    zustellreferenz: r.zustellreferenz,
    zielgebiet: r.ort,
    beladung: r.belVon,
    soll_ankunft: r.sollAnkunft,
    ist_ankunft: r.istAnkunft,
    status: 'MATCH',
    entfernung_km: r.distanceKm != null ? String(r.distanceKm) : null,
    geo_match: r.matchMethod === 'BBOX' ? 'JA' : r.matchMethod === 'DISTANZ' ? 'DISTANZ' : 'NEIN',
    tourdatum: r.tourdatum,
    typ: 'ZUSTELLUNG'
  }));

  let written = 0;
  if (rows.length) {
    const BATCH = 500;
    for (let i = 0; i < rows.length; i += BATCH) {
      const batch = rows.slice(i, i + BATCH);
      const { error: upsertErr } = await sb.from('fleetboard_arrivals')
        .upsert(batch, { onConflict: 'tour_nr,zustellreferenz,soll_ankunft' });
      if (upsertErr) {
        console.error(`Upsert Batch ${i}: ${upsertErr.message}`);
      } else {
        written += batch.length;
      }
    }
  }
  console.log(`\n${written}/${matchedResults.length} gematchte Stopps in fleetboard_arrivals aktualisiert.`);

  // workflow_runs Eintrag (Monitoring-Pflicht)
  const duration = Date.now() - t0;
  await sb.from('workflow_runs').insert({
    workflow_id: 'fleetboard2/matcher',
    status: 'success',
    vm: process.env.COMPUTERNAME || 'unknown',
    started_at: new Date(t0).toISOString(),
    finished_at: new Date().toISOString(),
    metrics: {
      tours_matched: matched.length,
      tours_pending: pending.length,
      tours_total: results.length,
      unknown_refs: unknown.length,
      begegnungsverkehr: bvCount,
      gps_points_loaded: totalTraces,
      duration_ms: duration
    },
    agent_id: 'fleetboard2-agent',
    trigger: 'scheduled-task'
  });

  console.log('Done.');
}

const t0 = Date.now();
main().catch(async e => {
  console.error('FATAL:', e.message);
  await sb.from('workflow_runs').insert({
    workflow_id: 'fleetboard2/matcher',
    status: 'error',
    vm: process.env.COMPUTERNAME || 'unknown',
    started_at: new Date(t0).toISOString(),
    finished_at: new Date().toISOString(),
    error_message: e.message,
    agent_id: 'fleetboard2-agent',
    trigger: 'scheduled-task'
  }).catch(() => {});
  process.exit(1);
});