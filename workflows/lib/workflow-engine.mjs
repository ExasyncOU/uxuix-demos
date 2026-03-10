#!/usr/bin/env node
/**
 * Exasync Workflow Engine
 *
 * Manages module freeze/unfreeze, integrity checks, and registry building.
 * Usage:
 *   node workflow-engine.mjs build          — Rebuild registry from source files
 *   node workflow-engine.mjs freeze <id>    — Freeze a module (requires all gates passed)
 *   node workflow-engine.mjs unfreeze <id>  — Unfreeze a module for editing
 *   node workflow-engine.mjs check          — Verify integrity of all frozen modules
 *   node workflow-engine.mjs serve          — Start local HTTP server for dashboard
 *   node workflow-engine.mjs validate <wf>  — Validate a workflow definition
 */

import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, dirname, extname, basename } from 'path';
import { createHash } from 'crypto';
import { fileURLToPath } from 'url';
import { createServer } from 'http';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const REGISTRY_PATH = join(ROOT, 'modules', 'registry.json');
const WORKFLOWS_DIR = join(ROOT, 'workflows');

// ============================================================
//  REGISTRY
// ============================================================

function loadRegistry() {
  if (!existsSync(REGISTRY_PATH)) return { modules: {} };
  return JSON.parse(readFileSync(REGISTRY_PATH, 'utf-8'));
}

function saveRegistry(registry) {
  registry.generatedAt = new Date().toISOString();
  writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2), 'utf-8');
  console.log(`[Registry] Saved to ${REGISTRY_PATH}`);
}

// ============================================================
//  FILE HASH
// ============================================================

function hashFile(filePath) {
  if (!existsSync(filePath)) return null;
  const content = readFileSync(filePath, 'utf-8');
  return createHash('sha256').update(content).digest('hex').slice(0, 16);
}

function hashContent(content) {
  return createHash('sha256').update(content).digest('hex').slice(0, 16);
}

// ============================================================
//  FREEZE / UNFREEZE
// ============================================================

function freezeModule(moduleId) {
  const registry = loadRegistry();
  const mod = registry.modules[moduleId];

  if (!mod) {
    console.error(`[Freeze] Modul "${moduleId}" nicht in Registry gefunden.`);
    process.exit(1);
  }

  if (mod.status === 'frozen') {
    console.log(`[Freeze] "${moduleId}" ist bereits frozen (v${mod.version}).`);
    return;
  }

  // Gate check
  const gates = mod.gate || {};
  if (!gates.passed || gates.score !== '11/11') {
    console.error(`[Freeze] ABGELEHNT — "${moduleId}" hat Gate ${gates.score || '?/11'}.`);
    console.error(`         Alle 11 Gates muessen bestanden sein.`);
    process.exit(1);
  }

  // Compute hash from embedded code
  const contentHash = mod.code ? hashContent(mod.code) : null;

  mod.status = 'frozen';
  mod.frozenAt = new Date().toISOString();
  mod.frozenBy = 'workflow-engine';
  mod.fileHash = contentHash;

  saveRegistry(registry);
  console.log(`[Freeze] "${moduleId}" v${mod.version} erfolgreich eingefroren.`);
  console.log(`         Hash: ${contentHash}`);
}

function unfreezeModule(moduleId, reason) {
  const registry = loadRegistry();
  const mod = registry.modules[moduleId];

  if (!mod) {
    console.error(`[Unfreeze] Modul "${moduleId}" nicht gefunden.`);
    process.exit(1);
  }

  if (mod.status !== 'frozen') {
    console.log(`[Unfreeze] "${moduleId}" ist nicht frozen.`);
    return;
  }

  // Bump minor version
  const parts = mod.version.split('.').map(Number);
  parts[1] += 1;
  parts[2] = 0;
  mod.version = parts.join('.');

  mod.status = 'draft';
  mod.frozenAt = null;
  mod.frozenBy = null;
  mod.unfreezeReason = reason || 'Manual unfreeze';
  mod.unfrozenAt = new Date().toISOString();

  saveRegistry(registry);
  console.log(`[Unfreeze] "${moduleId}" aufgetaut → v${mod.version} (draft)`);
  console.log(`           Grund: ${reason || 'nicht angegeben'}`);
}

// ============================================================
//  INTEGRITY CHECK
// ============================================================

function checkIntegrity() {
  const registry = loadRegistry();
  const modules = Object.values(registry.modules);
  let ok = 0, warn = 0, fail = 0;

  console.log('=== Integrity Check ===\n');

  for (const mod of modules) {
    if (mod.status !== 'frozen') {
      console.log(`  [SKIP] ${mod.id} — nicht frozen (${mod.status})`);
      continue;
    }

    if (!mod.fileHash) {
      console.log(`  [WARN] ${mod.id} — kein Hash gespeichert`);
      warn++;
      continue;
    }

    const currentHash = mod.code ? hashContent(mod.code) : null;
    if (currentHash === mod.fileHash) {
      console.log(`  [OK]   ${mod.id} v${mod.version} — Hash stimmt`);
      ok++;
    } else {
      console.log(`  [FAIL] ${mod.id} — Hash Mismatch! Erwartet: ${mod.fileHash}, Ist: ${currentHash}`);
      fail++;
    }
  }

  console.log(`\n=== Ergebnis: ${ok} OK, ${warn} WARN, ${fail} FAIL ===`);
  if (fail > 0) process.exit(1);
}

// ============================================================
//  WORKFLOW VALIDATION
// ============================================================

function validateWorkflow(workflowFile) {
  const wfPath = join(WORKFLOWS_DIR, workflowFile);
  if (!existsSync(wfPath)) {
    console.error(`[Validate] Workflow nicht gefunden: ${wfPath}`);
    process.exit(1);
  }

  const wf = JSON.parse(readFileSync(wfPath, 'utf-8'));
  const registry = loadRegistry();
  let errors = 0;

  console.log(`=== Validiere Workflow: ${wf.name} (${wf.id}) ===\n`);

  // Check all referenced modules exist and are frozen
  for (const step of wf.steps || []) {
    const modId = step.module;
    const mod = registry.modules[modId];

    if (!mod) {
      console.log(`  [FAIL] Step "${step.id}": Modul "${modId}" nicht in Registry`);
      errors++;
      continue;
    }

    if (mod.status !== 'frozen') {
      console.log(`  [FAIL] Step "${step.id}": Modul "${modId}" ist nicht frozen (${mod.status})`);
      errors++;
    } else {
      console.log(`  [OK]   Step "${step.id}": ${modId} v${mod.version} (frozen)`);
    }
  }

  // Check guardrails exist
  if (!wf.guardrails) {
    console.log(`  [WARN] Keine Guardrails definiert`);
  } else {
    if (!wf.guardrails.constraints) console.log(`  [WARN] Keine Constraints definiert`);
    if (!wf.guardrails.variables || wf.guardrails.variables.length === 0) console.log(`  [WARN] Keine Variablen definiert`);
    if (!wf.schedule) console.log(`  [WARN] Kein Schedule definiert`);
  }

  // Check connections are valid
  const stepIds = new Set((wf.steps || []).map(s => s.id));
  for (const step of wf.steps || []) {
    for (const nextId of step.next || []) {
      if (!stepIds.has(nextId)) {
        console.log(`  [FAIL] Step "${step.id}": next "${nextId}" existiert nicht`);
        errors++;
      }
    }
  }

  console.log(`\n=== Ergebnis: ${errors === 0 ? 'VALID' : `${errors} FEHLER`} ===`);
  if (errors > 0) process.exit(1);
}

// ============================================================
//  LOCAL SERVER (for dashboard)
// ============================================================

function serve(port = 3847) {
  const MIME = {
    '.html': 'text/html', '.json': 'application/json',
    '.js': 'text/javascript', '.mjs': 'text/javascript',
    '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml'
  };

  const server = createServer((req, res) => {
    let filePath = join(ROOT, req.url === '/' ? 'index.html' : req.url);

    if (!existsSync(filePath)) {
      res.writeHead(404);
      res.end('Not Found');
      return;
    }

    if (statSync(filePath).isDirectory()) {
      filePath = join(filePath, 'index.html');
    }

    const ext = extname(filePath);
    const mime = MIME[ext] || 'application/octet-stream';

    res.writeHead(200, {
      'Content-Type': `${mime}; charset=utf-8`,
      'Access-Control-Allow-Origin': '*'
    });
    res.end(readFileSync(filePath));
  });

  server.listen(port, () => {
    console.log(`\n  Exasync Workflow Monitor`);
    console.log(`  http://localhost:${port}\n`);
    console.log(`  Druecke Ctrl+C zum Beenden.\n`);
  });
}

// ============================================================
//  CLI
// ============================================================

const [,, cmd, ...args] = process.argv;

switch (cmd) {
  case 'freeze':
    if (!args[0]) { console.error('Usage: node workflow-engine.mjs freeze <module-id>'); process.exit(1); }
    freezeModule(args[0]);
    break;

  case 'unfreeze':
    if (!args[0]) { console.error('Usage: node workflow-engine.mjs unfreeze <module-id> [reason]'); process.exit(1); }
    unfreezeModule(args[0], args.slice(1).join(' '));
    break;

  case 'check':
    checkIntegrity();
    break;

  case 'validate':
    if (!args[0]) { console.error('Usage: node workflow-engine.mjs validate <workflow.json>'); process.exit(1); }
    validateWorkflow(args[0]);
    break;

  case 'serve':
    serve(parseInt(args[0]) || 3847);
    break;

  default:
    console.log(`
  Exasync Workflow Engine

  Befehle:
    freeze <module-id>              Modul einfrieren (alle 11 Gates noetig)
    unfreeze <module-id> [grund]    Modul auftauen fuer Bearbeitung
    check                           Integritaet aller frozen Module pruefen
    validate <workflow.json>        Workflow-Definition validieren
    serve [port]                    Lokalen Server starten (default: 3847)
    `);
}
