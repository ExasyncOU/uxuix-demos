# Infrastructure Templates

VM-Provisioning Templates fuer Claude Code Web (vom Handy aus nutzbar via `/new-vm`).

## Verzeichnisse

```
infrastructure/
├── cloud-init/                 # User-Data Scripts (Ubuntu 24.04)
│   ├── cx22-base.yml           # Minimal: SSH, ufw, fail2ban, unattended-upgrades
│   ├── cx22-linkedin.yml       # + Chrome, Node 22, xrdp, xfce4, Playwright deps
│   └── cx22-pipeline.yml       # + Python 3.12, Docker, Supabase CLI
├── firewall-rules.json         # Standard-Firewall (SSH+RDP nur B-Hive)
└── README.md
```

## Convention

| Template | Use-Case | Type | Cost (mo) |
|---|---|---|---|
| `cx22-base` | Trading-Bot, kleine Worker | cx22 hel1 | ~3.79 EUR + 0.50 IPv4 |
| `cx22-linkedin` | LinkedIn Multi-Account VM (Browser-Workload) | cx22 hel1 | ~3.79 EUR + 0.50 IPv4 |
| `cx22-pipeline` | Pipeline-Kunden-VM (Python+Docker) | cx22 nbg1 | ~3.79 EUR + 0.50 IPv4 |

## Wie aufrufen

**Vom Handy** (Claude iOS App auf claude.ai/code, Repo `ExasyncOU/uxuix-demos`):
```
Setze neue VM auf: vm-key=linkedin-bodo-2, template=cx22-linkedin, tenant=exasync, location=hel1
```
→ Claude fuehrt `/new-vm` Skill aus, provisioniert, schreibt in `wfm_v3.vms`, antwortet mit IP

**Aus Terminal:**
```bash
claude --remote "Setze VM 'kunde-mueller-pipeline' mit cx22-pipeline Template fuer Tenant 'mueller-gmbh' auf"
```

## Vorausssetzungen im Cloud-Environment

Im Environment `exasync-vm-provisioning` (claude.ai/code → Settings → Environments) muessen folgende Env-Vars gesetzt sein:
- `HCLOUD_TOKEN` (aus Vault `hetzner-cloud-api`)
- `SUPABASE_SERVICE_ROLE_KEY` (aus Vault `supabase-main`)
- `SUPABASE_ACCESS_TOKEN` (fuer Supabase MCP, aus Vault `supabase-access-token`)
- `GH_TOKEN` (aus Vault `github-exasync-classic`, optional fuer gh-CLI)

Setup-Script installiert: `hcloud`, `terraform`, `supabase-cli`, `jq`, `gh`.
