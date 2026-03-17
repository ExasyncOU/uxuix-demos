/**
 * Fleetboard 2.0 — Shared Library
 *
 * Supabase-Client, Cache-Pfade, Cache lesen/schreiben.
 * Wird von allen Fleetboard 2.0 Scripts importiert.
 */

import { createClient } from '@supabase/supabase-js';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const CACHE_DIR = join(__dirname, 'cache');
export const CACHE_FILE = join(CACHE_DIR, 'geodata.json');

// --- .env laden (ohne dotenv-Dependency) ---
const envPath = join(__dirname, '.env');
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq > 0) {
      const key = trimmed.slice(0, eq).trim();
      const val = trimmed.slice(eq + 1).trim();
      if (!process.env[key]) process.env[key] = val;
    }
  }
}

// --- Supabase ---
const SB_URL = process.env.SUPABASE_URL || 'https://crslpxgwxjmovrhyxiim.supabase.co';
const SB_KEY = process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_ANON_KEY;
if (!SB_KEY) { console.error('SUPABASE_SERVICE_KEY oder SUPABASE_ANON_KEY fehlt'); process.exit(1); }
export const sb = createClient(SB_URL, SB_KEY);

// --- Cache lesen ---
export function loadCache() {
  if (!existsSync(CACHE_FILE)) return null;
  return JSON.parse(readFileSync(CACHE_FILE, 'utf8'));
}

// --- Cache schreiben ---
export function writeCache(data) {
  if (!existsSync(CACHE_DIR)) mkdirSync(CACHE_DIR, { recursive: true });
  writeFileSync(CACHE_FILE, JSON.stringify(data, null, 2));
}
