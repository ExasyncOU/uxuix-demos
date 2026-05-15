# uxuix-demos — Claude Code Instructions (Repo-Scope)

Dieses Repo wird von **Claude Code on the Web** (claude.ai/code) genutzt. Cloud-Sessions clonen es, also liegen alle nötigen Regeln **im Repo**, nicht im User-Home.

## Was in diesem Repo passiert

1. **Workflow Monitor** (`/workflows/`) → deployed auf GitHub Pages: `https://exasyncou.github.io/uxuix-demos/workflows`
   - Single Source of Truth für alle Pipeline-Zustände
   - Strukturen: `list.json`, `<slug>.workflow.json`, `modules/registry.json`
2. **Demo-Pages** für Kunden (`index.html`, `hohenester-demo.html`, etc.)
3. **VM-Provisioning Templates** (`/infrastructure/`)

## ABSOLUTE REGELN

### R8: Workflow Monitor = Single Source of Truth
- Jeder Eintrag in `workflows/list.json` braucht eine `workflows/<id>.workflow.json`
- Jede `workflow.json` braucht: `lanes[]`, `steps[]`, `source`, `monitoring`
- Jeder `step.module` muss als Key in `workflows/modules/registry.json` existieren
- Registry-Module brauchen: `source.lines`, `source.size`, `code`, `source.type`

### R9: Workflow-Vollstaendigkeits-Check vor jedem Deploy
Vor `git push` Skill aufrufen: `.claude/skills/workflow-monitor-deploy.md` (11-Punkte-Check)

### R10b: Bei Aenderung an Modulen/Steps
Drei Stellen synchron updaten: `<slug>.workflow.json` + `modules/registry.json` + Quelle (Gist SHA / VM-Pfad). Skill: `.claude/skills/pipeline-fix-from-logs.md`

### R13: Echte Umlaute
In Prosa/Docs/Commit-Messages: ä, ö, ü, ß. NICHT ae/oe/ue/ss.
Ausnahmen: Dateinamen, JSON-Keys, Bash-Variable, falls Encoding-Problem droht.

### R14: Credential-Vault-Lookup VOR jeder Token-Frage
Credentials liegen in `public.credential_vault` (Supabase). NIE in Files. Via Env-Var injizieren:
```
HCLOUD_TOKEN, SUPABASE_SERVICE_ROLE_KEY, GH_TOKEN
```

### R17: Post-Deploy-Validate
Nach jedem Workflow-Monitor-Deploy: Verifikation in der UI (öffne `https://exasyncou.github.io/uxuix-demos/workflows`, prüfe Swimlane + Code + History Tab).

### R18: VMs aus `wfm_v3.vms` querien
Nach VM-Provisioning: INSERT in `wfm_v3.vms`. Nie hardcoden — immer von dort lesen.

## Skills verfügbar

| Skill | Wann |
|---|---|
| `.claude/skills/workflow-monitor-deploy.md` | Vor jedem Push der `workflows/` ändert |
| `.claude/skills/vm-provision-hetzner.md` | Beim Anfordern „setze VM auf für …" |
| `.claude/skills/pipeline-fix-from-logs.md` | Wenn Bodo sagt „workflow X ist rot, fix" |

## Agents

`.claude/agents/workflow-monitor.md` — Operativer Agent für list.json/workflow.json/registry.json
`.claude/agents/vm-provisioning.md` — Hetzner-VM-Provisioning + wfm_v3.vms INSERT

## MCP Servers

Aktiviert über `.mcp.json`:
- **supabase** — `wfm_v3.*`, `credential_vault`, `workflow_runs`
- **context7** — Library-Docs (hcloud, terraform, supabase-cli, playwright)

## Geheimnisse

**KEINE Secrets committen.** Tokens kommen als Env-Vars vom Cloud-Environment:
- `HCLOUD_TOKEN` — Hetzner Cloud API (Vault: `hetzner-cloud-api`)
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase SRK (Vault: `supabase-main.service_role_key`)
- `GH_TOKEN` — GitHub PAT für gh-CLI (Vault: `github-exasync-classic`)

Diese Variablen sind im Cloud-Environment „exasync-vm-provisioning" hinterlegt (in claude.ai/code → Settings → Environments).

## Sprache der Antworten an Bodo

Deutsch mit echten Umlauten (siehe R13). Knapp. Bei Code-Änderungen: Pfad + Zeile zeigen. Bei VM-Aufgaben: IP + Vault-Verweis am Ende.
