---
name: workflow-monitor-deploy
description: 11-Punkte-Konsistenz-Check fuer Workflow Monitor. Bevor irgendetwas in workflows/ committed wird, MUSS dieser Skill durchlaufen werden. Verhindert leere Tabs, 404er, "Lade Workflow..." Haenger.
---

# Workflow Monitor Deploy Check

Bevor du `git push` ausfuehrst auf einem Commit, der `workflows/` aendert: alle 11 Punkte verifizieren. **Ein FAIL = kein Push.**

## Checklist

### Strukturelle Konsistenz

**WM1** — Jeder Eintrag in `workflows/list.json` hat eine `workflows/<id>.workflow.json`
```bash
jq -r '.workflows[].id' workflows/list.json | while read id; do
  test -f "workflows/${id}.workflow.json" || echo "MISSING: ${id}.workflow.json"
done
```

**WM2** — Jede `workflow.json` hat Top-Level: `lanes[]`, `steps[]`, `source`, `monitoring`
```bash
for f in workflows/*.workflow.json; do
  jq -e '.lanes and .steps and .source and .monitoring' "$f" >/dev/null || echo "INCOMPLETE: $f"
done
```

**WM3** — Jeder Step hat: `id`, `lane`, `module`, `label`, `next`
```bash
for f in workflows/*.workflow.json; do
  jq -e '[.steps[] | (.id and .lane and .module and .label and (.next | type=="array"))] | all' "$f" >/dev/null || echo "STEP MISSING FIELDS: $f"
done
```

**WM4** — Jede `lane` aus `steps[]` existiert in `lanes[]`
```bash
for f in workflows/*.workflow.json; do
  jq -e '([.steps[].lane] | unique) - ([.lanes[].id] | unique) | length == 0' "$f" >/dev/null || echo "UNKNOWN LANE: $f"
done
```

### Registry-Konsistenz

**WM5** — `source.files[]` Module sind in `steps[].module` referenziert (umgekehrt nicht zwingend)

**WM6** — Registry-Module haben: `source.lines`, `source.size`, `code`
```bash
jq -r '.modules | to_entries[] | select(.value.source.lines == null or .value.source.size == null or .value.code == null) | .key' workflows/modules/registry.json
```
Output muss leer sein.

**WM6b** — Registry-Module haben `source.type` (`github-gist` | `github-repo` | `vm-only` | `inline`)
```bash
jq -r '.modules | to_entries[] | select(.value.source.type == null) | .key' workflows/modules/registry.json
```

**WM7** — Kein Workflow mit `status="disabled"` ohne `stages` UND ohne `steps` (= Geist-Workflow)

**WM8** — Jeder `step.module` aus jeder workflow.json existiert als Key in `modules/registry.json.modules`
```bash
ALL_MODULES=$(jq -r '.modules | keys[]' workflows/modules/registry.json)
for f in workflows/*.workflow.json; do
  jq -r '.steps[].module' "$f" | while read m; do
    echo "$ALL_MODULES" | grep -qx "$m" || echo "MISSING REGISTRY ENTRY: $m (referenced by $f)"
  done
done
```

**WM9** — Registry-Key === internes `id`-Feld === `step.module`
```bash
jq -r '.modules | to_entries[] | select(.value.id != .key) | "MISMATCH: key=\(.key) id=\(.value.id)"' workflows/modules/registry.json
```

**WM10** — Registry `source.sha` muss aktuellem Gist-SHA entsprechen
- Pro Modul mit `source.type=github-gist`: GET `https://api.github.com/gists/<gist_id>`
- Vergleichen `files[<filename>].raw_url` SHA-Anteil mit `registry.json source.sha`

## Pass/Fail

- **11/11 (oder 10/10 bei vm-only Modulen):** Push erlaubt
- **<11:** Liste die Punkte auf, schlage Fix vor, KEIN PUSH

## Post-Deploy-Verifikation (R17)

Nach Push (GitHub Pages braucht ~30s):
1. Oeffne `https://exasyncou.github.io/uxuix-demos/workflows`
2. Pruefe geaenderter Workflow: Swimlane-Tab + Code-Tab + History-Tab
3. Wenn ein Tab "Laedt..." anzeigt: Browser-DevTools Network, suche 404
4. Bei 404: das fehlende File committen, pushen, erneut pruefen

## Lessons learned

**Incident 20.03.2026:** WM8+WM9 fehlten als Check → `step.module='nacke/email-notifications'`, aber `registry.json` hatte `nacke/nacke-email`. Code-Tab blieb leer ohne Fehler. Diese Checks verhindern das stille Versagen.
