---
name: pipeline-fix-from-logs
description: Analysiert pipeline_logs + pipeline_errors aus wfm_v3, identifiziert Root-Cause, schlaegt Fix vor. Use when Bodo says "workflow X ist rot", "fix nacke pipeline", "check pipeline_errors".
---

# Pipeline Fix from Logs

Standardisierter Fix-Workflow fuer rote Pipelines. Liest DB, identifiziert Root-Cause, oeffnet PR — kein direkter Push auf main.

## Voraussetzungen

- Supabase MCP aktiv (in `.mcp.json`)
- `SUPABASE_SERVICE_ROLE_KEY` als Env-Var im Cloud-Environment

## Workflow

### 1. Letzter Lauf des Workflows finden

```sql
SELECT id, started_at, status, error_details
FROM public.workflow_runs
WHERE workflow = '<slug>'
ORDER BY started_at DESC
LIMIT 5;
```

Erwartung: letzter `status='error'` oder `'warning'` ist der Kandidat.

### 2. Logs des Laufs lesen

```sql
SELECT timestamp, level, message,
       module_id, section_id, step_id,
       metadata->>'fallback_kind' AS fallback_kind,
       metadata->>'fallback_outcome' AS fallback_outcome,
       metadata->>'resolution' AS resolution
FROM wfm_v3.pipeline_logs
WHERE workflow_run_id = '<run-id-aus-1>'
  AND level IN ('ERROR', 'WARN')
ORDER BY timestamp ASC;
```

### 3. Pipeline-Errors abrufen

```sql
SELECT pe.error_signature, pe.module_id, m.module_key, pe.error_message,
       pe.metadata->>'fallback_attached' AS fallback_attached
FROM wfm_v3.pipeline_errors pe
LEFT JOIN wfm_v3.modules m ON m.id = pe.module_id
WHERE pe.workflow_run_id = '<run-id>';
```

### 4. Wiederkehrendes Pattern pruefen (Mneme)

```sql
SELECT pattern_name, root_cause, solution_key, prevention_rule, occurrence_count, status
FROM public.error_patterns
WHERE error_signature ILIKE '%<keywords-aus-error>%'
  AND status IN ('active', 'recurring')
ORDER BY occurrence_count DESC
LIMIT 5;
```

### 5. Modul-Source lesen

Aus dem Repo:
```bash
jq -r ".modules[\"<module_key>\"].code" workflows/modules/registry.json
```

Oder aus DB (Live-Stand):
```sql
SELECT mv.code, mv.gist_sha, mv.lines
FROM wfm_v3.module_versions mv
JOIN wfm_v3.modules m ON m.current_version_id = mv.id
WHERE m.module_key = '<module_key>';
```

### 6. Fix vorschlagen

Output an Bodo:
```
## Pipeline <slug> — Fix-Vorschlag

**Run-ID:** <uuid>
**Fehler-Signatur:** <error_signature>
**Modul:** <module_key> (Z. <line>)
**Wiederkehrend:** ja/nein (occurrence_count=N)

### Root Cause
<analyse>

### Vorgeschlagener Fix
```diff
- <alte-zeile>
+ <neue-zeile>
```

### Aenderungs-Pfad (R10b)
1. `workflows/modules/registry.json` Eintrag `<key>.code` und `source.lines`/`source.size`
2. `workflows/<workflow-slug>.workflow.json` `source.currentSHA` (falls Gist)
3. `wfm_v3.module_versions` INSERT neuer Version + `wfm_v3.modules.current_version_id` UPDATE
4. Falls VM-Modul: Source-Datei auf Ziel-VM via SCP (Bodo macht, NICHT Cloud-Claude)
5. Post-Deploy-Validate via `A.I.D.A/v3/scripts/post_deploy_validate.py <slug> --fix` (Bodo lokal)

### Error Pattern Update
```sql
UPDATE public.error_patterns
SET occurrence_count = occurrence_count + 1,
    last_seen = NOW()
WHERE pattern_name = '<pattern-name>';
```

### PR-Vorschlag
Branch: `fix/<slug>-<kurz-bezeichnung>`
Title: `fix(<slug>): <was geaendert>`
```

### 7. PR erstellen (wenn Bodo OK gibt)

```bash
git checkout -b fix/<slug>-<change>
git add workflows/modules/registry.json workflows/<slug>.workflow.json
git commit -m "fix(<slug>): <was>

Co-Authored-By: claude-flow <ruv@ruv.net>"
git push -u origin fix/<slug>-<change>
gh pr create --title "fix(<slug>): <was>" --body "<details>"
```

## VERBOTEN

- Fix ohne `pipeline_logs`-Analyse vorschlagen (= Bauchgefuehl)
- Direkter Push auf main (immer PR)
- Pipeline neu starten ohne `error_patterns`-Check (R16)
- Fix vorschlagen ohne den 5-Stellen-Sync (Registry + Workflow + module_versions + VM-Source + Validate) zu erwaehnen
