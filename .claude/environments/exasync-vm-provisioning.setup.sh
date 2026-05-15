#!/bin/bash
# Setup-Script fuer Cloud-Environment "exasync-vm-provisioning"
# Wird einmalig beim ersten Session-Start ausgefuehrt, danach gecached (5min Budget)
#
# Dieses Skript ist die REFERENZ — der eigentliche Inhalt muss in claude.ai/code
# unter Settings → Environments → "exasync-vm-provisioning" → Setup script kopiert werden.

set -e

echo "=== Installing tools for Exasync VM-Provisioning + Workflow-Monitor ==="

# 1. Hetzner Cloud CLI
echo "[1/4] hcloud CLI..."
curl -fsSL https://github.com/hetznercloud/cli/releases/latest/download/hcloud-linux-amd64.tar.gz \
  | tar -xz -C /usr/local/bin hcloud

# 2. Supabase CLI (fuer wfm_v3 Migrations + SQL)
echo "[2/4] supabase CLI..."
curl -fsSL https://github.com/supabase/cli/releases/latest/download/supabase_linux_amd64.tar.gz \
  | tar -xz -C /usr/local/bin

# 3. GitHub CLI (Cloud hat den nicht pre-installed)
echo "[3/4] gh CLI..."
apt-get update && apt-get install -y gh

# 4. PostgreSQL Client + jq (jq ist meist da, aber sicher ist sicher)
echo "[4/4] psql + jq..."
apt-get install -y postgresql-client jq

echo "=== Done. Tool versions: ==="
hcloud version
supabase --version
gh --version | head -1
psql --version
jq --version

echo ""
echo "=== Required Env-Vars (set in Environment Config): ==="
echo "  HCLOUD_TOKEN           — Vault: hetzner-cloud-api"
echo "  SUPABASE_SERVICE_ROLE_KEY — Vault: supabase-main.service_role_key"
echo "  SUPABASE_ACCESS_TOKEN  — Vault: supabase-access-token (fuer MCP)"
echo "  GH_TOKEN               — Vault: github-exasync-classic"
