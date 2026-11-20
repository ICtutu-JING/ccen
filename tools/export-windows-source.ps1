#requires -Version 5.1
<#
.SYNOPSIS
Create a PRIVATE, allowlisted source export of ClaudeConnectionManager.
.DESCRIPTION
Read-only with respect to the source and running services. Does not export the
installed EXE, account/profile data, proxy settings, or credentials. Does not
upload, build, install, stop, or restart anything. Review the PRIVATE export
before sharing it; the credential scan is heuristic and is not a safety proof.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$SourceRoot = (Join-Path $env:USERPROFILE 'Documents\New project\ClaudeConnectionManager'),
    [ValidateNotNullOrEmpty()]
    [string]$DestinationRoot = (Join-Path $env:USERPROFILE ('Downloads\ccen-windows-source-PRIVATE-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FullDirectoryPath([string]$Path) {
    # PowerShell's current location can differ from the process working directory.
    $full = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path))
    if ($full -eq [IO.Path]::GetPathRoot($full)) { return $full }
    return $full.TrimEnd([char[]]'\/')
}

function Test-Within([string]$Child, [string]$Parent) {
    return $Child.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or
        $Child.StartsWith($Parent.TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparseAncestors([string]$Path) {
    # A plain leaf underneath a junction is also a redirected path. Check every
    # existing ancestor, including destination parents that would redirect writes.
    $probe = $Path
    while ($probe) {
        if (Test-Path -LiteralPath $probe) {
            if (((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Source and destination paths must not contain symlink or junction ancestors.'
            }
        }
        $parent = [IO.Directory]::GetParent($probe)
        if ($null -eq $parent) { break }
        $probe = $parent.FullName
    }
}

$source = Get-FullDirectoryPath $SourceRoot
$destination = Get-FullDirectoryPath $DestinationRoot
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw 'Source directory not found. Supply -SourceRoot with the actual source folder, not the installed EXE folder.'
}
if ($source -eq [IO.Path]::GetPathRoot($source)) {
    throw 'Source must be a project directory, not a filesystem root.'
}
if (Test-Within $destination $source) {
    throw 'Destination must be outside the source directory.'
}
if (Test-Path -LiteralPath $destination) {
    throw 'Destination already exists. Choose a new directory; nothing will be overwritten.'
}
Assert-NoReparseAncestors $source
Assert-NoReparseAncestors $destination

# Skip directories before descending; do not follow junctions/symlinks.
$excludedDirectories = @(
    '.git', '.svn', '.hg', '.venv', 'venv', 'env', 'node_modules',
    '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    'build', 'dist', '_internal', 'logs', 'log', 'state', 'sessions',
    'profiles', 'browser_profiles', 'user_data', 'userdata', 'cache',
    '.claude', '.codex', 'config', 'configs', 'settings', 'secrets',
    'backup', 'backups', '.idea', '.vscode'
)
$textExtensions = @('.py', '.pyw', '.cjs', '.js', '.spec', '.ps1', '.bat', '.cmd', '.qss', '.ui', '.qrc', '.html', '.css')
$assetExtensions = @('.ico', '.icns', '.png', '.svg')
$excludedNamePattern = '(?i)(secret|credential|cookie|session|oauth|token|password|account|private[-_]?key|\.local\.|\.env(?:\.|$))'
$credentialRules = [ordered]@{
    'private-key' = '-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----'
    'service-token' = '(?i)\b(?:sk-ant-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})'
    'credential-in-url' = '(?i)\b(?:https?|socks[45]h?)://[^\s/:"''<>]+:[^\s/@"''<>]+@'
    'authorization-header' = '(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=-]{16,}'
    'literal-secret' = '(?i)["'']?\b(?:(?:[a-z][a-z0-9]*[_-])+|(?:proxy|upstream|auth)[_-]?)?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|username|user|password|passwd|pass|pwd|client[_-]?secret|secret)["'']?[ \t]*(?::[ \t]*[a-z_][a-z0-9_.\[\], |]*)?[ \t]*[:=][ \t]*["''][^"''\r\n]+["'']'
}

$queue = New-Object 'System.Collections.Generic.Queue[string]'
$candidates = New-Object 'System.Collections.Generic.List[object]'
$findings = New-Object 'System.Collections.Generic.List[string]'
$omissions = New-Object 'System.Collections.Generic.List[object]'
$queue.Enqueue($source)
while ($queue.Count -gt 0) {
    $current = $queue.Dequeue()
    Assert-NoReparseAncestors $current
    foreach ($entry in Get-ChildItem -LiteralPath $current -Force) {
        $relative = $entry.FullName.Substring($source.Length + 1)
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $omissions.Add([pscustomobject]@{ RelativePath = $relative; Reason = 'reparse-point-not-followed' })
            continue
        }
        if ($entry.PSIsContainer) {
            if ($excludedDirectories -notcontains $entry.Name) {
                $queue.Enqueue($entry.FullName)
            }
            else {
                $omissions.Add([pscustomobject]@{ RelativePath = $relative; Reason = 'excluded-directory-not-traversed' })
            }
            continue
        }
        if ($entry.Name -match $excludedNamePattern) {
            $omissions.Add([pscustomobject]@{ RelativePath = $relative; Reason = 'sensitive-filename' })
            continue
        }
        $extension = $entry.Extension.ToLowerInvariant()
        $isRequirements = $entry.Name -match '^requirements(?:[-_.][A-Za-z0-9_-]+)?\.txt$'
        $isText = ($textExtensions -contains $extension) -or $isRequirements
        $isAsset = $assetExtensions -contains $extension
        if (-not ($isText -or $isAsset)) {
            $omissions.Add([pscustomobject]@{ RelativePath = $relative; Reason = 'not-allowlisted' })
            continue
        }
        if ($entry.Length -gt 5MB) {
            throw ('Allowlisted file exceeds 5 MiB; review it separately: ' + $entry.Name)
        }
        if ($isText -or $extension -eq '.svg') {
            Assert-NoReparseAncestors $entry.FullName
            $content = [IO.File]::ReadAllText($entry.FullName)
            foreach ($rule in $credentialRules.GetEnumerator()) {
                if ($content -match $rule.Value) {
                    # Report relative path and rule only, never the matched value.
                    $findings.Add($relative + ' [' + $rule.Key + ']')
                }
            }
        }
        $candidates.Add([pscustomobject]@{ File = $entry; Relative = $relative })
    }
}

if ($findings.Count -gt 0) {
    Write-Warning 'Potential embedded credentials found. No export directory has been created.'
    foreach ($finding in $findings) { Write-Warning $finding }
    throw 'Review the flagged source locally. Export only a sanitized copy; do not paste credential values into chat or GitHub.'
}
if ($candidates.Count -eq 0) {
    throw 'No allowlisted source files found. An EXE plus _internal is an installed build, not a source export.'
}
if (-not ($candidates | Where-Object { $_.File.Extension -in @('.py', '.pyw', '.cjs', '.js') })) {
    throw 'No Python or JavaScript source found. Locate the original project before exporting.'
}

New-Item -ItemType Directory -Path $destination | Out-Null
@'
PRIVATE SOURCE EXPORT - NOT READY FOR PUBLICATION

This is an allowlisted copy for private inspection, not a full source backup.
No application behavior, dependencies, build, or credential safety is certified.
The scanner is heuristic. Review every file, image, hardcoded address, user path,
configuration default, and source comment before sharing or adding it to Git.
Do not upload this directory automatically. Personalize sanitized templates in a
separate checkout. Config/state/logs/profiles/binaries and JSON are excluded.
EXPORT-OMISSIONS.csv records skipped entries; excluded directories are not listed
recursively. Legitimate dependency manifests and config modules may be missing.
EXPORT-COMPLETE.txt is written only after all files and inventories are written.
Without it, treat this directory as a failed, incomplete export.
This export contains no running-state receipt and cannot prove current routing.
'@ | Set-Content -LiteralPath (Join-Path $destination 'PRIVATE-READ-BEFORE-SHARING.txt') -Encoding UTF8

$manifest = New-Object 'System.Collections.Generic.List[object]'
foreach ($candidate in ($candidates | Sort-Object Relative)) {
    $target = Join-Path $destination $candidate.Relative
    $targetDirectory = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $targetDirectory)) {
        New-Item -ItemType Directory -Path $targetDirectory | Out-Null
    }
    Assert-NoReparseAncestors $candidate.File.FullName
    Assert-NoReparseAncestors $targetDirectory
    # Validate the bytes copied, including a second scan to catch a changed source.
    $sourceHash = (Get-FileHash -LiteralPath $candidate.File.FullName -Algorithm SHA256).Hash
    Copy-Item -LiteralPath $candidate.File.FullName -Destination $target
    $targetHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if ($sourceHash -ne $targetHash) { throw 'A source file changed during export. Discard this PRIVATE export and retry.' }
    if ($textExtensions -contains $candidate.File.Extension.ToLowerInvariant() -or
        $candidate.File.Extension -in @('.txt', '.svg')) {
        $copiedContent = [IO.File]::ReadAllText($target)
        foreach ($rule in $credentialRules.GetEnumerator()) {
            if ($copiedContent -match $rule.Value) {
                Remove-Item -LiteralPath $target -Force
                throw ('A copied file failed the credential scan and was removed. Discard this PRIVATE export: ' + $candidate.Relative)
            }
        }
    }
    $manifest.Add([pscustomobject]@{
        RelativePath = $candidate.Relative
        Bytes = (Get-Item -LiteralPath $target).Length
        SHA256 = $targetHash.ToLowerInvariant()
    })
}
$manifest | Export-Csv -LiteralPath (Join-Path $destination 'SOURCE-MANIFEST.csv') -NoTypeInformation -Encoding UTF8
if ($omissions.Count -gt 0) {
    $omissions | Sort-Object RelativePath | Export-Csv -LiteralPath (Join-Path $destination 'EXPORT-OMISSIONS.csv') -NoTypeInformation -Encoding UTF8
}
else {
    '"RelativePath","Reason"' | Set-Content -LiteralPath (Join-Path $destination 'EXPORT-OMISSIONS.csv') -Encoding UTF8
}
@'
Allowlisted export operation completed. This does not certify project completeness,
credential safety, a reproducible build, or current application behavior.
Review SOURCE-MANIFEST.csv, EXPORT-OMISSIONS.csv and the PRIVATE marker together.
'@ | Set-Content -LiteralPath (Join-Path $destination 'EXPORT-COMPLETE.txt') -Encoding UTF8
Write-Host ('PRIVATE export created: ' + $destination)
Write-Host ('Source files copied: ' + $manifest.Count)
Write-Host 'Review this private directory before sharing. Nothing was uploaded; no running settings were changed.'
