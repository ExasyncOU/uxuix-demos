---
description: Diagnostiziert + fixt eine rote Pipeline durch Log-Analyse
argument-hint: <workflow-slug>
---

Workflow-Slug: $ARGUMENTS

Nutze den Agent `workflow-monitor` und das Skill `pipeline-fix-from-logs` um die Pipeline zu fixen.

**Vorgehen:**
1. Letzten failed Run aus `public.workflow_runs WHERE workflow = '$ARGUMENTS'` lesen
2. `wfm_v3.pipeline_logs` + `wfm_v3.pipeline_errors` fuer diesen Run analysieren
3. `public.error_patterns` auf wiederkehrendes Pattern pruefen
4. Root-Cause + Fix-Vorschlag formulieren
5. PR auf neuem Branch `fix/${ARGUMENTS}-<kurz>` oeffnen, NICHT direkt auf main pushen

Antworte mit:
- Run-ID, Fehler-Signatur, betroffenes Modul
- Root-Cause-Analyse (1-2 Saetze)
- Diff-Vorschlag
- 5-Stellen-Sync-Pfad (Registry + Workflow + module_versions + VM-Source + post_deploy_validate)
- PR-Link nach Erstellung
