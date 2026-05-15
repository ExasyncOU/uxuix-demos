---
name: vm-provision-hetzner
description: Provisioniert Hetzner Cloud VM via hcloud-CLI. Use this skill when Bodo asks for "neue VM", "setze Maschine auf", or "clone social-media VM Setup". Includes wfm_v3.vms INSERT and mail-pool assignment.
---

# Hetzner VM Provisioning

Setzt eine Hetzner Cloud VM auf, registriert sie in `wfm_v3.vms`, optional mit Mail-Pool-Zuordnung.

## Voraussetzungen (im Cloud-Environment "exasync-vm-provisioning")

- `hcloud` CLI installiert (im Setup-Script)
- `HCLOUD_TOKEN` als Env-Var (aus `credential_vault.hetzner-cloud-api`)
- `SUPABASE_SERVICE_ROLE_KEY` als Env-Var (fuer wfm_v3 INSERT)
- `hcloud context use exasync` oder Token direkt: `export HCLOUD_TOKEN=...`

## Schritte

### 1. Inputs (von Bodo)

| Input | Beispiel | Pflicht |
|---|---|---|
| `vm-key` | `linkedin-bodo-2`, `kunde-mueller-pipeline` | Ja (kebab-case, eindeutig) |
| `template` | `cx22-base`, `cx22-linkedin`, `cx22-pipeline` | Ja |
| `tenant-slug` | `exasync`, `wuensche`, `nacke-logistik` | Ja |
| `location` | `hel1` (Helsinki), `nbg1` (Nuernberg), `fsn1` (Falkenstein) | Default: `hel1` |
| `mail-service` | `uxuix-bot`, `uxuix-automation`, `social-media-vm` | Optional |

### 2. Pre-Check

```bash
# Pruefen ob vm-key schon existiert
psql "$SUPABASE_DB_URL" -c "SELECT vm_key, vm_ip FROM wfm_v3.vms WHERE vm_key='<vm-key>';"
# Falls Zeile vorhanden: ABBRUCH, anderen Namen waehlen
```

### 3. SSH-Key + Firewall vorbereiten

```bash
# SSH-Key (one-time, falls noch nicht angelegt)
hcloud ssh-key list -o columns=id,name | grep b-hive-master || \
  hcloud ssh-key create --name b-hive-master --public-key-from-file ~/.ssh/id_ed25519.pub

# Firewall (one-time, dann wiederverwenden)
FW_ID=$(hcloud firewall list -o columns=id,name | grep social-media-access | awk '{print $1}')
if [ -z "$FW_ID" ]; then
  hcloud firewall create --name social-media-access \
    --rules-file infrastructure/firewall-rules.json
  FW_ID=$(hcloud firewall list -o columns=id,name | grep social-media-access | awk '{print $1}')
fi
```

### 4. VM erstellen

```bash
hcloud server create \
  --name "<vm-key>" \
  --type cx22 \
  --image ubuntu-24.04 \
  --location <location> \
  --ssh-key b-hive-master \
  --firewall "$FW_ID" \
  --user-data-from-file "infrastructure/cloud-init/<template>.yml" \
  --label "tenant=<tenant-slug>" \
  --label "managed-by=claude-code-web"
```

Output speichern: `IPV4=$(hcloud server describe <vm-key> -o format='{{.PublicNet.IPv4.IP}}')`

### 5. Cloud-Init Status pruefen

```bash
sleep 60  # warten bis User-Data durchgelaufen
ssh -o StrictHostKeyChecking=no root@${IPV4} 'cloud-init status --wait'
# Expected: status: done. Bei "error" → Logs: cat /var/log/cloud-init-output.log
```

### 6. wfm_v3.vms INSERT (R18)

```sql
INSERT INTO wfm_v3.vms (
  vm_key, vm_ip, hetzner_type, ram_gb, vcpu, storage_gb,
  location, ssh_user, ssh_access, ssh_method, tenant_id, notes
) VALUES (
  '<vm-key>', '<IPV4>', 'cx22', 4, 2, 40,
  '<location>', 'root', 'B-Hive-only', 'ssh-key-b-hive-master',
  (SELECT id FROM wfm_v3.tenants WHERE slug='<tenant-slug>'),
  'Provisioned via Claude Code Web on ' || NOW()::date::text
);
```

Via Supabase MCP:
```
mcp__supabase__execute_sql project_id=crslpxgwxjmovrhyxiim query="..."
```

### 7. Mail-Pool-Zuordnung (optional)

```sql
INSERT INTO wfm_v3.vm_mail_assignments (vm_id, mail_service_name)
VALUES (
  (SELECT id FROM wfm_v3.vms WHERE vm_key='<vm-key>'),
  '<mail-service>'
);
```

Trigger prueft VM-Lock (`mail_accounts.restricted_to_vm_keys`). Bei Fehler: Mail ist auf andere VM gepinnt.

### 8. Antwort an Bodo

```
VM "<vm-key>" angelegt.
- IPv4: <IPV4>
- Type: cx22 in <location>
- SSH: ssh root@<IPV4> (B-Hive only)
- wfm_v3.vms: eingetragen
- Mail-Account: <mail-service> (falls gesetzt)

Naechste Schritte:
- Anwendung deployen (via SCP von B-Hive aus, Cloud-Claude hat keinen SSH-Zugriff)
- Bei LinkedIn-VM: einmaliger Manual-Login per RDP nach Cloud-Init
```

## Wiederverwendung: Bestehende VM clonen via Snapshot

```bash
# Snapshot von existierender VM erstellen
hcloud server create-image --type snapshot --description "social-media-base" 127816983

# Neue VM aus Snapshot
hcloud server create --name <neuer-name> --type cx22 --image <snapshot-id> ...
```

## VERBOTEN

- VM ohne `wfm_v3.vms` INSERT liegen lassen (R18)
- Production-VM ohne Bodos explizite Bestaetigung anlegen
- Hardcoded HCLOUD_TOKEN — IMMER aus `${HCLOUD_TOKEN}` Env-Var (R14)
- IPv4 weglassen wenn LinkedIn/Browser-Workload geplant (Manual-Login per RDP braucht IPv4)
