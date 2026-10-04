# LocalMesh Agent — Windows installer (M9, FR-AGT-05 / §18.6 / §21.6)
#
# Run from an ELEVATED PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass; .\install-agent.ps1
#
# What it does:
#   1. Creates a per-service local account (or uses a provided one).
#   2. Installs the Agent wheel into a dedicated venv (pipx-style layout).
#   3. Adds the FR-AGT-05 firewall rule: inbound TCP 8443, Private profile
#      ONLY (Domain kept administrable; Public NEVER opened).
#   4. Registers the Agent as a Windows service (auto start).
#   5. Hardens the data dir ACL to the service account (§17.6 platform gap
#      documented in config.py: ensure_data_dir handles POSIX 0700; the
#      Windows ACL is completed HERE by the installer).
#
# The installer NEVER enables dev-insecure mode and NEVER writes secrets to
# disk outside the owner-only data dir (§17.6).

$ErrorActionPreference = "Stop"

# --- configurable ------------------------------------------------------------
$AgentPort     = 8443
$AdminPort     = 8444
$ServiceName   = "LocalMeshAgent"
$InstallRoot   = "$env:ProgramData\LocalMesh"
$DataDir       = "$env:LOCALAPPDATA\LocalMesh\agent"
$VenvDir       = "$InstallRoot\venv"
$ServiceUser   = "NT AUTHORITY\NetworkService"
# -----------------------------------------------------------------------------

Write-Host "== LocalMesh Agent install =="

# 1. Python is a prerequisite (3.12+); the Agent is a wheel install (ADR-002).
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.12+ is required but was not found in PATH."
}

# 2. Virtualenv layout.
python -m venv "$VenvDir"
& "$VenvDir\Scripts\python.exe" -m pip install --upgrade pip
& "$VenvDir\Scripts\python.exe" -m pip install localmesh-agent

# 3. FR-AGT-05: firewall rule scoped to the Private profile ONLY.
$existing = Get-NetFirewallRule -DisplayName "LocalMesh Agent (Private)" -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName "LocalMesh Agent (Private)"
}
New-NetFirewallRule -DisplayName "LocalMesh Agent (Private)" `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort $AgentPort `
    -Profile Private | Out-Null
Write-Host "Firewall: inbound TCP $AgentPort allowed on the Private profile only."

# 4. Data dir ACL: service account + Administrators, nothing else (§17.6).
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
icacls $DataDir /inheritance:r /grant:r "${ServiceUser}:(OI)(CI)F" `
    /grant:r "Administrators:(OI)(CI)F" | Out-Null

# 5. Windows service registration (sc.exe; the Agent runs TLS 1.3-only by
#    default, §17.3 — no extra TLS flags here on purpose).
$binPath = "`"$VenvDir\Scripts\python.exe`" -m localmesh_agent run --config `"$DataDir\config.toml`""
sc.exe create $ServiceName binPath= $binPath start= auto obj= $ServiceUser
sc.exe description $ServiceName "LocalMesh Agent — secure LAN mesh inference (§13)"
sc.exe failure $ServiceName reset= 86400 actions= restart/5000/restart/10000/restart/30000

Write-Host "== Installed. Start with: sc.exe start $ServiceName =="
Write-Host "Next: pair a phone via the admin API on 127.0.0.1:$AdminPort (ADR-014)."
