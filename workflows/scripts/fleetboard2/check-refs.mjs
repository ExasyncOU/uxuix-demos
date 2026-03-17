#!/usr/bin/env node
/**
 * Fleetboard 2.0 — Zustellreferenzen pruefen
 *
 * Liest den lokalen Geodaten-Cache und prueft eine Tourenabfrage-CSV
 * auf unbekannte Zustellreferenzen. Unbekannte werden in Supabase
 * (fleetboard_unknown_refs) gemeldet und sind im Workflow Monitor sichtbar.
 *
 * Usage:
 *   node check-refs.mjs tour.csv   # CSV pruefen, unbekannte Refs melden
 *   node check-refs.mjs            # Nur offene unbekannte Refs anzeigen
 */

import { readFileSync } from 'fs';
import { sb, loadCache } from './lib.mjs';

function findUnknownRefs(csvPath, refLookup) {
  const raw = readFileSync(csvPath, 'latin1');
  const lines = raw.split('\n').filter(l => l.trim());
  if (lines.length < 2) return [];
  const headers = lines[0].replace(/;$/, '').split(';').map(h => h.trim().replace(/"/g, ''));
  const zrefIdx = headers.findIndex(h => /zustellref/i.test(h));
  if (zrefIdx === -1) { console.error('Spalte "Zustellreferenz" nicht in CSV'); return []; }
  const unknown = [];
  const seen = new Set();
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].replace(/;$/, '').split(';').map(c => c.trim().replace(/"/g, ''));
    const zref = cols[zrefIdx];
    if (!zref || seen.has(zref)) continue;
    seen.add(zref);
    if (!refLookup[zref]) unknown.push({ zustellreferenz: zref });
  }
  return unknown;
}

async function reportUnknown(refs) {
  if (!refs.length) { console.log('Alle Zustellreferenzen bekannt.'); return; }
  console.log(`\n${refs.length} UNBEKANNTE Zustellreferenzen:`);
  for (const r of refs) {
    console.log(`  - ${r.zustellreferenz}`);
    await sb.from('fleetboard_unknown_refs').upsert({
      zustellreferenz: r.zustellreferenz,
      last_seen_at: new Date().toISOString(),
      seen_count: 1, resolved: false
    }, { onConflict: 'zustellreferenz' });
  }
}

async function showOpenRefs() {
  const { data: open } = await sb.from('fleetboard_unknown_refs')
    .select('zustellreferenz, seen_count, last_seen_at')
    .eq('resolved', false).order('last_seen_at', { ascending: false }).limit(10);
  if (open?.length) {
    console.log(`\n--- ${open.length} offene unbekannte Refs ---`);
    open.forEach(r => console.log(`  ${r.zustellreferenz} (${r.seen_count}x)`));
  } else {
    console.log('\nKeine offenen unbekannten Refs.');
  }
}

async function main() {
  const csvPath = process.argv[2];
  console.log('=== Fleetboard 2.0 — Zustellreferenzen pruefen ===\n');
  const cache = loadCache();
  if (!cache) { console.error('Kein Geodaten-Cache. Bitte: node sync-geodata.mjs'); process.exit(1); }
  console.log(`Cache vom ${cache.cached_at} (${Object.keys(cache.refLookup).length} Refs)`);
  if (csvPath) {
    const unknown = findUnknownRefs(csvPath, cache.refLookup);
    await reportUnknown(unknown);
  }
  await showOpenRefs();
  console.log('\nDone.');
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
