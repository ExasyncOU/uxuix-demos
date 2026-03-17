#!/usr/bin/env node
/**
 * Fleetboard 2.0 — Tourenplanung abrufen (IMAP)
 *
 * Holt die neueste Tourenabfrage-CSV aus dem Postfach gvlog@uxuix.de.
 * Die CSV kommt taeglich ~17:00 als Email-Anhang.
 * Dieses Script laeuft taeglich um 10:00 und holt die CSV vom Vortag.
 *
 * Usage:
 *   node fetch-tours.mjs              # neueste CSV holen
 *
 * Env:
 *   IMAP_HOST     (default: w00f31fe.kasserver.com)
 *   IMAP_PORT     (default: 993)
 *   IMAP_USER     (default: gvlog@uxuix.de)
 *   IMAP_PASS     (required)
 */

import { ImapFlow } from 'imapflow';
import { writeFileSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import './lib.mjs'; // .env Auto-Loader

const __dirname = dirname(fileURLToPath(import.meta.url));
const CSV_DIR = join(__dirname, 'cache');

const IMAP_HOST = process.env.IMAP_HOST || 'w00f31fe.kasserver.com';
const IMAP_PORT = parseInt(process.env.IMAP_PORT || '993');
const IMAP_USER = process.env.IMAP_USER || 'gvlog@uxuix.de';
const IMAP_PASS = process.env.IMAP_PASS;

if (!IMAP_PASS) {
  console.error('IMAP_PASS muss gesetzt sein');
  process.exit(1);
}

async function main() {
  console.log('=== Fleetboard 2.0 — Tourenplanung abrufen ===\n');
  console.log(`IMAP: ${IMAP_USER} @ ${IMAP_HOST}:${IMAP_PORT}`);

  const client = new ImapFlow({
    host: IMAP_HOST,
    port: IMAP_PORT,
    secure: true,
    auth: { user: IMAP_USER, pass: IMAP_PASS },
    tls: { rejectUnauthorized: false },
    logger: false
  });

  await client.connect();
  console.log('Verbunden.\n');

  const lock = await client.getMailboxLock('INBOX');
  try {
    const since = new Date();
    since.setHours(since.getHours() - 48);

    const messages = [];
    for await (const msg of client.fetch(
      { since, seen: false },
      { envelope: true, bodyStructure: true, uid: true }
    )) {
      messages.push(msg);
    }

    for await (const msg of client.fetch(
      { since, seen: true },
      { envelope: true, bodyStructure: true, uid: true }
    )) {
      messages.push(msg);
    }

    console.log(`${messages.length} Emails in den letzten 48h gefunden.`);

    let bestMsg = null;
    let bestPart = null;
    let bestName = null;

    for (const msg of messages) {
      const parts = flattenParts(msg.bodyStructure);
      for (const p of parts) {
        const name = partFilename(p);
        if (name && /tourenabfrage.*\.csv$/i.test(name)) {
          if (!bestName || name > bestName) {
            bestMsg = msg;
            bestPart = p;
            bestName = name;
          }
        }
      }
    }

    if (!bestMsg) {
      console.log('Keine Tourenabfrage-CSV in den letzten 48h gefunden.');
      process.exit(0);
    }

    const csvName = partFilename(bestPart);
    console.log(`\nNeueste CSV: ${csvName} (Email: ${bestMsg.envelope.date.toISOString()})`);

    const { content } = await client.download(bestMsg.seq.toString(), bestPart.part);
    const chunks = [];
    for await (const chunk of content) chunks.push(chunk);
    const csvBuffer = Buffer.concat(chunks);

    if (!existsSync(CSV_DIR)) mkdirSync(CSV_DIR, { recursive: true });
    const outPath = join(CSV_DIR, csvName);
    writeFileSync(outPath, csvBuffer);
    console.log(`Gespeichert: ${outPath} (${csvBuffer.length} Bytes)`);

  } finally {
    lock.release();
  }

  await client.logout();
  console.log('\nDone.');
}

function flattenParts(structure, prefix = '') {
  const result = [];
  if (!structure) return result;
  if (structure.childNodes) {
    for (let i = 0; i < structure.childNodes.length; i++) {
      result.push(...flattenParts(structure.childNodes[i], prefix ? `${prefix}.${i + 1}` : `${i + 1}`));
    }
  } else {
    structure.part = prefix || '1';
    result.push(structure);
  }
  return result;
}

function partFilename(part) {
  if (part.dispositionParameters?.filename) return part.dispositionParameters.filename;
  if (part.parameters?.name) return part.parameters.name;
  return null;
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
