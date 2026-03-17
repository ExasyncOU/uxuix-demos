#!/usr/bin/env node
/**
 * Fleetboard 2.0 — Geodaten Sync
 *
 * Liest Areas (inkl. Zustellreferenzen) aus Supabase, cached lokal als JSON.
 * Kann auch neue Zustellreferenzen zu einer Area hinzufuegen.
 *
 * Usage:
 *   node sync-geodata.mjs                                      # Areas laden + cachen
 *   node sync-geodata.mjs --add-ref "Koch Hamburg" "WM Fulda"  # Ref zu Area hinzufuegen
 */

import { sb, writeCache, CACHE_FILE } from './lib.mjs';

async function fetchAreas() {
  const { data, error } = await sb.from('fleetboard_areas')
    .select('area_id, name, lat_min, lat_max, lon_min, lon_max, zustellreferenzen, is_heimat')
    .order('name');
  if (error) throw new Error('Areas laden: ' + error.message);
  return data;
}

function buildAndCache(areas) {
  const refLookup = {};
  for (const a of areas) {
    for (const ref of (a.zustellreferenzen || [])) {
      refLookup[ref] = {
        area_id: a.area_id, name: a.name,
        lat_min: a.lat_min, lat_max: a.lat_max,
        lon_min: a.lon_min, lon_max: a.lon_max,
        is_heimat: a.is_heimat || false
      };
    }
  }
  const cache = { areas, refLookup, cached_at: new Date().toISOString() };
  writeCache(cache);
  console.log(`Cache: ${areas.length} Areas, ${Object.keys(refLookup).length} Zustellreferenzen -> ${CACHE_FILE}`);
  return cache;
}

async function addRef(zref, areaName) {
  const { data: area } = await sb.from('fleetboard_areas')
    .select('area_id, zustellreferenzen').eq('name', areaName).single();
  if (!area) { console.error(`Area "${areaName}" nicht gefunden`); return false; }
  const refs = area.zustellreferenzen || [];
  if (refs.includes(zref)) { console.log(`"${zref}" ist schon bei "${areaName}"`); return true; }
  refs.push(zref);
  const { error } = await sb.from('fleetboard_areas')
    .update({ zustellreferenzen: refs, updated_at: new Date().toISOString() })
    .eq('area_id', area.area_id);
  if (error) { console.error('Update fehlgeschlagen:', error.message); return false; }
  await sb.from('fleetboard_unknown_refs')
    .update({ resolved: true, resolved_at: new Date().toISOString(), resolved_to_area: areaName })
    .eq('zustellreferenz', zref);
  console.log(`"${zref}" -> "${areaName}" hinzugefuegt`);
  return true;
}

async function main() {
  const args = process.argv.slice(2);
  console.log('=== Fleetboard 2.0 — Geodaten Sync ===\n');
  if (args[0] === '--add-ref' && args[1] && args[2]) await addRef(args[1], args[2]);
  const areas = await fetchAreas();
  buildAndCache(areas);
  console.log('\nDone.');
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
