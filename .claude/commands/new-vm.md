---
description: Provisioniert eine neue Hetzner-VM ueber den vm-provisioning Agent
argument-hint: <vm-key> <template> <tenant-slug> [location]
---

Nutze den Agent `vm-provisioning` und das Skill `vm-provision-hetzner` um eine neue Hetzner-VM aufzusetzen.

**Argumente:** $ARGUMENTS

**Vorgehen:**
1. Inputs validieren (vm-key kebab-case, template existiert in `infrastructure/cloud-init/`)
2. Pre-Check: `vm-key` darf in `wfm_v3.vms` noch nicht existieren
3. `hcloud server create` mit dem entsprechenden cloud-init Template
4. Nach Provisioning: `wfm_v3.vms` INSERT + optional Mail-Pool-Zuordnung
5. Antwort an Bodo mit IP, SSH-Befehl, naechsten Schritten

Falls Argumente unvollstaendig: frag Bodo nach den fehlenden Werten BEVOR `hcloud server create` ausgefuehrt wird.
