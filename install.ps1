<#
.SYNOPSIS
  Installs the architecture-diagrams skill for GitHub Copilot (VS Code agent mode and Copilot CLI).

.DESCRIPTION
  Copies skill\architecture-diagrams\ to the personal skills folder
  %USERPROFILE%\.copilot\skills\architecture-diagrams, which VS Code and Copilot CLI both read.
  With -Project <workspace>, copies it to <workspace>\.github\skills\architecture-diagrams instead.
  <workspace> is the folder you open in VS Code or start Copilot CLI in: the one holding the
  cloned repos, not one repo inside it. The scanner skips folders named architecture-diagrams,
  so the installed skill is never scanned as code.
  Then checks for Python 3.9 or newer. No network access. Works in Windows PowerShell 5.1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Project C:\work\claims
#>
[CmdletBinding()]
param(
    # the folder that holds the cloned repos (the one opened in VS Code or Copilot CLI)
    [string]$Project = ''
)

$ErrorActionPreference = 'Stop'
$SkillName = 'architecture-diagrams'

$source = Join-Path (Join-Path $PSScriptRoot 'skill') $SkillName
if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md'))) {
    Write-Host "Cannot find the skill at $source. Run install.ps1 from the folder that holds 'skill\$SkillName'." -ForegroundColor Red
    exit 1
}

if ($Project -ne '') {
    if (-not (Test-Path -LiteralPath $Project -PathType Container)) {
        Write-Host "The folder $Project does not exist." -ForegroundColor Red
        exit 1
    }
    $projectRoot = (Resolve-Path -LiteralPath $Project).Path
    $skillsRoot = Join-Path (Join-Path $projectRoot '.github') 'skills'
    $where = "project skill for the workspace $projectRoot"
} else {
    if (-not $env:USERPROFILE) {
        Write-Host 'USERPROFILE is not set; cannot find your home folder.' -ForegroundColor Red
        exit 1
    }
    $skillsRoot = Join-Path (Join-Path $env:USERPROFILE '.copilot') 'skills'
    $where = 'personal skill'
}
$target = Join-Path $skillsRoot $SkillName

# ---------------------------------------------------------------- copy the skill
if (Test-Path -LiteralPath $target) {
    Write-Host "Replacing the existing copy at $target"
    Remove-Item -LiteralPath $target -Recurse -Force   # drop files from an older version
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force
}
Get-ChildItem -LiteralPath $target -Recurse -Force -Directory |
    Where-Object { $_.Name -eq '__pycache__' } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Installed the $where at $target" -ForegroundColor Green

# ---------------------------------------------------------------- find Python 3.9+
$candidates = @(
    @{ Exe = 'py'; Args = @('-3') },
    @{ Exe = 'python'; Args = @() },
    @{ Exe = 'python3'; Args = @() }
)
$found = $null
$seen = @()
foreach ($c in $candidates) {
    if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
    $cmdArgs = $c.Args + @('--version')
    try {
        $ver = (& $c.Exe @cmdArgs 2>&1 | Out-String).Trim()
    } catch {
        continue
    }
    if ($LASTEXITCODE -ne 0 -or $ver -notmatch 'Python (\d+)\.(\d+)') { continue }
    $seen += "$($c.Exe) $($c.Args -join ' ') -> $ver"
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {   # needs (3, 9) or newer
        $found = $c
        break
    }
}

if ($null -eq $found) {
    Write-Host ''
    Write-Host 'Python 3.9 or newer was not found (tried: py -3, python, python3).' -ForegroundColor Yellow
    if ($seen.Count -gt 0) { Write-Host ('Found only: ' + ($seen -join '; ')) }
    Write-Host 'To fix it:'
    Write-Host '  1. Install Python 3.9 or newer from your company software portal, or from python.org.'
    Write-Host '     The Microsoft Store version also works.'
    Write-Host '  2. During setup, tick "Add python.exe to PATH" (or install the "py" launcher).'
    Write-Host '  3. Open a new terminal and check: python --version'
    Write-Host '  4. If "python" opens the Microsoft Store instead, turn off the "python.exe" App execution'
    Write-Host '     alias in Settings > Apps > Advanced app settings > App execution aliases.'
    Write-Host 'The skill is installed and will work once Python is available.'
    exit 2
}

$pythonCmd = (@($found.Exe) + $found.Args) -join ' '
Write-Host "Python OK: $pythonCmd ($ver)" -ForegroundColor Green

# ---------------------------------------------------------------- adjust the VS Code task template
$tasks = Join-Path (Join-Path $target 'assets') 'tasks.json'
if (Test-Path -LiteralPath $tasks) {
    $text = [System.IO.File]::ReadAllText($tasks)
    if ($Project -ne '') {
        $text = $text.Replace('${userHome}/.copilot/skills/', '${workspaceFolder}/.github/skills/')
    }
    if ($found.Exe -ne 'python') {
        $extra = ''
        foreach ($a in $found.Args) { $extra += '"' + $a + '", ' }
        $text = $text.Replace('"command": "python",', '"command": "' + $found.Exe + '",')
        $text = $text.Replace('"args": [', '"args": [' + $extra)
    }
    [System.IO.File]::WriteAllText($tasks, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host ''
Write-Host 'Next:'
Write-Host '  1. Clone all the repos you want on the diagrams into one folder.'
Write-Host '  2. Open that folder in VS Code (Copilot chat in agent mode) or start Copilot CLI in it.'
Write-Host '     In Copilot CLI, run /skills reload if a session was already open.'
Write-Host '  3. Ask: "Draw the landscape for these repos."'
Write-Host "If Copilot cannot run commands, run them yourself, for example:"
Write-Host "  $pythonCmd `"$target\scripts\run.py`" scan --workspace `"<folder with the repos>`""
exit 0
