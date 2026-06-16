<#
.SYNOPSIS
  Build and optionally push the play.infra.ai Docker image to the registry.

.DESCRIPTION
  The build context is the project directory so the Dockerfile can
  reference the application source.

.USAGE
  .\build_and_push.ps1 [-Tag <string>] [-Push] [-EnableCopilot $false] [-EnableTerraform $false] ...

  -Tag                Image tag (default: 1.0.0)
  -Push               Actually push the image after building (opt-in)
  -EnableCopilot      Include GitHub Copilot SDK (default: $true)
  -EnableClaude       Include Claude Agent SDK (default: $true)
  -EnableCursor       Include Cursor SDK (default: $true)
  -EnableAntigravity  Include Google Antigravity SDK (default: $true)
  -EnableCodex        Include Codex SDK (default: $true)
  -EnableGh           Include gh CLI binary (default: $true)
#>

[CmdletBinding()]
param(
    [string]$Tag = "1.0.0",
    [switch]$Push,
    [bool]$EnableCopilot = $true,
    [bool]$EnableClaude = $true,
    [bool]$EnableCursor = $true,
    [bool]$EnableAntigravity = $true,
    [bool]$EnableCodex = $true,
    [bool]$EnableGh = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Registry  = "registry.example.com"
$Repo      = "myproject"
$ImageName = "harness-template"
$TargetImage = "$Registry/$Repo/${ImageName}:${Tag}"

# The build context is the directory containing this script.
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildContext = $ScriptDir
$DockerFile   = Join-Path $ScriptDir "Dockerfile"

try {
    Write-Host "Target image  : $TargetImage"
    Write-Host "Build context : $BuildContext"
    Write-Host "Dockerfile    : $DockerFile"

    Write-Host "`nBuilding image..."
    docker build --no-cache `
        -f $DockerFile `
        -t $TargetImage `
        --build-arg ENABLE_COPILOT=$($EnableCopilot.ToString().ToLower()) `
        --build-arg ENABLE_CLAUDE=$($EnableClaude.ToString().ToLower()) `
        --build-arg ENABLE_CURSOR=$($EnableCursor.ToString().ToLower()) `
        --build-arg ENABLE_ANTIGRAVITY=$($EnableAntigravity.ToString().ToLower()) `
        --build-arg ENABLE_CODEX=$($EnableCodex.ToString().ToLower()) `
        --build-arg ENABLE_GH=$($EnableGh.ToString().ToLower()) `
        $BuildContext

    if ($Push) {
        Write-Host "`nLogging into registry: $Registry"
        docker login $Registry
        
        Write-Host "`nPushing image..."
        docker push $TargetImage
    }
    else {
        Write-Host "`nPush skipped. Re-run with -Push to push the image."
    }
}
catch {
    Write-Error "Operation failed: $_"
    exit 1
}
