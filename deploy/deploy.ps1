# Moroska Orders - Remote Deploy Script
# Purpose: Pull latest changes from git and restart systemd service on AWS server

param(
    [string]$Server = "16.171.38.174",
    [string]$User = "ubuntu",
    [string]$KeyPath = "C:\Users\danil\my-aws-server-key.pem",
    [string]$ProjectDir = "/home/ubuntu/moroska"
)

# Colors for output
$Colors = @{
    Success = "Green"
    Error = "Red"
    Info = "Cyan"
    Warning = "Yellow"
}

function Write-Status {
    param([string]$Message, [string]$Type = "Info")
    Write-Host $Message -ForegroundColor $Colors[$Type]
}

function Invoke-SSH {
    param([string]$Command)

    $sshArgs = @(
        "-i", $KeyPath,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "$User@$Server",
        $Command
    )

    Write-Host "Executing: $Command" -ForegroundColor Gray
    & ssh @sshArgs
    return $LASTEXITCODE
}

function Invoke-SSHOutput {
    param([string]$Command)

    $sshArgs = @(
        "-i", $KeyPath,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "$User@$Server",
        $Command
    )

    $output = & ssh @sshArgs 2>&1
    return $output
}

# Check if key exists
if (-not (Test-Path $KeyPath)) {
    Write-Status "SSH key not found at: $KeyPath" "Error"
    Pause
    exit 1
}

Write-Status "Starting deployment..." "Info"
Write-Status "Server: $Server | User: $User | Project: $ProjectDir" "Info"
Write-Host ""

# Step 1: Git Pull
Write-Status "Pulling latest changes from git..." "Info"
$pullResult = Invoke-SSH "cd $ProjectDir && git pull"
if ($LASTEXITCODE -ne 0) {
    Write-Status "Git pull failed" "Error"
    Pause
    exit 1
}
Write-Status "Git pull successful" "Success"
Write-Host ""

# Step 2: Reload systemd daemon (in case service file changed)
Write-Status "Reloading systemd daemon..." "Info"
$reloadResult = Invoke-SSH "sudo systemctl daemon-reload"
if ($LASTEXITCODE -ne 0) {
    Write-Status "Systemd daemon reload had issues (may be non-critical)" "Warning"
}
Write-Status "Systemd daemon reloaded" "Success"
Write-Host ""

# Step 3: Restart the service
Write-Status "Restarting moroska service..." "Info"
$restartResult = Invoke-SSH "sudo systemctl restart moroska.service"
if ($LASTEXITCODE -ne 0) {
    Write-Status "Service restart failed" "Error"
    Pause
    exit 1
}
Write-Status "Service restart command sent" "Success"
Write-Host ""

# Step 4: Wait a moment for service to start
Write-Host "Waiting for service to start..." -ForegroundColor Gray
Start-Sleep -Seconds 2

# Step 5: Check service status
Write-Status "Checking service status..." "Info"
$statusOutput = Invoke-SSHOutput "systemctl status moroska.service --no-pager"

$statusText = $statusOutput -join "`n"
if ($statusText -match "Active: active \(running\)") {
    Write-Status "Service is RUNNING" "Success"
    Write-Host ""
    Write-Status "Service Status:" "Info"
    Write-Host $statusText -ForegroundColor Green
} else {
    Write-Status "Service status unclear, full output:" "Warning"
    Write-Host $statusText
}

Write-Host ""
Write-Status "Deployment complete!" "Success"
Write-Status "Changes have been pulled and service restarted with new code." "Info"

Pause
