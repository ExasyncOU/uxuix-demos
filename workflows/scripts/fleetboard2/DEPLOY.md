# Fleetboard 2.0 — Deploy-Anleitung

## Source of Truth
Dieses Verzeichnis (`workflows/scripts/fleetboard2/`) ist die **einzige** Quelle fuer alle Fleetboard 2.0 Scripts.

## Deploy auf VM
```bash
# Von B-Lab aus:
scp -i ~/.ssh/id_ed25519_uxuix_vm <script>.mjs administrator@157.180.78.163:C:/FleetboardScript/fleetboard2/
```

## Regel
- Scripts NUR hier aendern, dann auf VM deployen
- NIEMALS direkt per SCP auf VM schreiben ohne Repo-Update
- Nach jedem Deploy: SHA im Workflow Monitor aktualisieren

## Scripts
| Script | Schedule | Funktion |
|--------|----------|----------|
| lib.mjs | — | Shared Library (.env, Supabase, Cache) |
| fetch-positions.mjs | jede Minute | GPS-Positionen via SOAP API |
| fetch-tours.mjs | 10:00 CET | CSV per IMAP |
| match-tours.mjs | alle 15 min | GPS-Matching |
| sync-geodata.mjs | manuell | Geodaten-Cache |
| check-refs.mjs | manuell | Unbekannte Refs melden |

## VM
- Host: 157.180.78.163
- User: administrator
- Key: ~/.ssh/id_ed25519_uxuix_vm
- Pfad: C:\FleetboardScript\fleetboard2\
