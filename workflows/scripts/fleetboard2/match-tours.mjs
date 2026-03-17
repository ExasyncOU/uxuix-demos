#!/usr/bin/env node
/**
 * Fleetboard 2.0 — Tour-Matcher v2.1.0 (frozen 17.03.2026)
 *
 * Matcht GPS-Traces aus Supabase gegen die Tourenplanung-CSV.
 * Fuer jeden Stopp wird der Trace gesucht der am naechsten
 * zur geplanten Ankunftszeit (closest-to-soll) liegt.
 *
 * Features:
 * - closest-to-soll Matching (max 8h Delta)
 * - GVLOGMG Rueckkehr: nur nach letztem Zustellstopp der Tour
 * - GVLOGMG: nur geplantes Kennzeichen (kein Begegnungsverkehr)
 * - Trace-Deduplizierung (ein GPS-Punkt nur 1x verwendbar)
 * - Supabase Paginierung (.range() statt .limit())
 * - Null-safe Areas (lat_min=null)
 *
 * Usage:
 *   node match-tours.mjs                    # neueste CSV automatisch
 *   node match-tours.mjs path/to/tour.csv   # explizite CSV
 */

import { readFileSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { sb, loadCache, CACHE_DIR } from './lib.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DISTANCE_THRESHOLD_KM = 15;
const MAX_MATCH_DELTA_MS = 8 * 60 * 60 * 1000;
const normKz = kz => kz.replace(/[\s\-]/g, '').toUpperCase();

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
    tourBez: col('TourBez'), zref: col('Zustellreferenz'), emgOrt: col('EmgOrt')
  };
  const stops = [];
  for (let i = 1; i < lines.length; i++) {
    const c = lines[i].replace(/;$/, '').split(';').map(s => s.trim().replace(/"/g, ''));
    const zref = c[idx.zref];
    if (!zref) continue;
    stops.push({
      aufNr: c[idx.aufNr], tourNr: c[idx.tourNr], kennzeichen: c[idx.kz],
      tourBez: c[idx.tourBez], zustellreferenz: zref, ort: c[idx.emgOrt],
      belDat: c[idx.belDat]?.split(' ')[0] || null,
      sollAnkunft: combineDateTime(c[idx.entVonDat], c[idx.entVonZeit]),
      sollAbfahrt: combineDateTime(c[idx.entBisDat], c[idx.entBisZeit]),
      belVon: combineDateTime(c[idx.belVonDat], c[idx.belVonZeit])
    });
  }
  return stops;
}

function combineDateTime(datePart, timePart) {
  if (!datePart || !timePart) return null;
  const d = datePart.split(' ')[0];
  const t = timePart.split(' ')[1] || timePart.split(' ')[0];
  const [day, month, year] = d.split('.');
  return new Date(`${year}-${month}-${day}T${t}`);
}

function distanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

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

function findLatestCsv(dir) {
  const candidates = [dir, CACHE_DIR, join(__dirname, 'cache')];
  if (process.platform === 'win32') candidates.push('C:\\FleetboardScript');
  for (const csvDir of candidates) {
    if (!csvDir) continue;
    try {
      const files = readdirSync(csvDir)
        .filter(f => /^Tourenabfrage.*\.csv$/i.test(f))
        .sort().reverse();
      if (files.length) return join(csvDir, files[0]);
    } catch { /* dir not found */ }
  }
  return null;
}

async function main() {
  let csvPath = process.argv[2];
  if (!csvPath) {
    csvPath = findLatestCsv();
    if (!csvPath) { console.error('Keine Tourenabfrage-CSV gefunden'); process.exit(1); }
    console.log(`Auto-CSV: ${csvPath}`);
  }
  console.log('=== Fleetboard 2.0 — Tour-Matcher ===\n');
  const cache = loadCache();
  if (!cache) { console.error('Kein Geodaten-Cache. Erst: node sync-geodata.mjs'); process.exit(1); }
  console.log(`Cache: ${Object.keys(cache.refLookup).length} Zustellreferenzen`);
  const stops = parseTours(csvPath);
  console.log(`CSV: ${stops.length} Stopps\n`);
  const matchable = stops.filter(s => cache.refLookup[s.zustellreferenz])
    .sort((a, b) => (a.sollAnkunft || 0) - (b.sollAnkunft || 0));
  const unknown = stops.filter(s => !cache.refLookup[s.zustellreferenz] && s.zustellreferenz);
  console.log(`Matchable: ${matchable.length}, Unbekannte Refs: ${unknown.length}`);
  const platesRaw = [...new Set(matchable.map(s => s.kennzeichen))];
  const platesNorm = [...new Set(platesRaw.map(normKz))];
  console.log(`Fahrzeuge: ${platesRaw.join(', ')}\n`);

  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  yesterday.setHours(12, 0, 0, 0);
  const gpsFrom = yesterday.toISOString();
  const gpsTo = now.toISOString();
  const tracesByPlate = {};
  let totalTraces = 0;

  const { data: vehicleRows } = await sb.from('fleetboard_vehicles').select('kennzeichen');
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
        .gte('gps_time', gpsFrom).lte('gps_time', gpsTo)
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
      aufNr: stop.aufNr, tourNr: stop.tourNr, kennzeichen: stop.kennzeichen,
      actualKennzeichen: bestMatch?.kennzeichen || null, tourBez: stop.tourBez,
      zustellreferenz: stop.zustellreferenz, ort: stop.ort, tourdatum: stop.belDat,
      belVon: stop.belVon?.toISOString() || null,
      sollAnkunft: stop.sollAnkunft?.toISOString() || null,
      istAnkunft: bestMatch ? bestMatch.gps_time : null,
      status: bestMatch ? 'MATCHED' : 'AUSSTEHEND',
      matchMethod: bestMatch?.method || null,
      distanceKm: bestMatch?.distance_km ?? null,
      begegnungsverkehr: isSwap
    });
  }

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

  const rows = results.map(r => ({
    tour_nr: r.tourNr, tour_bez: r.tourBez, kennzeichen: normKz(r.kennzeichen),
    zustellreferenz: r.zustellreferenz, zielgebiet: r.ort, beladung: r.belVon,
    soll_ankunft: r.sollAnkunft, ist_ankunft: r.istAnkunft || null,
    status: r.status === 'MATCHED' ? 'MATCH' : 'AUSSTEHEND',
    entfernung_km: r.distanceKm != null ? String(r.distanceKm) : null,
    geo_match: r.matchMethod === 'BBOX' ? 'JA' : r.matchMethod === 'DISTANZ' ? 'DISTANZ' : 'NEIN',
    tourdatum: r.tourdatum, typ: 'ZUSTELLUNG'
  }));

  const BATCH = 500;
  let written = 0;
  for (let i = 0; i < rows.length; i += BATCH) {
    const batch = rows.slice(i, i + BATCH);
    const { error: upsertErr } = await sb.from('fleetboard_arrivals')
      .upsert(batch, { onConflict: 'tour_nr,zustellreferenz,soll_ankunft' });
    if (upsertErr) {
      const { error: insertErr } = await sb.from('fleetboard_arrivals').insert(batch);
      if (insertErr) { console.error(`Batch ${i}: ${insertErr.message}`); }
      else { written += batch.length; }
    } else { written += batch.length; }
  }
  console.log(`\n${written}/${rows.length} in fleetboard_arrivals geschrieben (upsert).`);

  const duration = Date.now() - t0;
  await sb.from('workflow_runs').insert({
    workflow_id: 'fleetboard2/matcher', status: 'success',
    vm: process.env.COMPUTERNAME || 'unknown',
    started_at: new Date(t0).toISOString(), finished_at: new Date().toISOString(),
    metrics: { tours_matched: matched.length, tours_pending: pending.length,
      tours_total: results.length, unknown_refs: unknown.length,
      begegnungsverkehr: bvCount, gps_points_loaded: totalTraces, duration_ms: duration },
    agent_id: 'fleetboard2-agent', trigger: 'scheduled-task'
  });
  console.log('Done.');
}

const t0 = Date.now();
main().catch(async e => {
  console.error('FATAL:', e.message);
  await sb.from('workflow_runs').insert({
    workflow_id: 'fleetboard2/matcher', status: 'error',
    vm: process.env.COMPUTERNAME || 'unknown',
    started_at: new Date(t0).toISOString(), finished_at: new Date().toISOString(),
    error_message: e.message, agent_id: 'fleetboard2-agent', trigger: 'scheduled-task'
  }).catch(() => {});
  process.exit(1);
});
