#requires -Version 5.1
<# Read Markdown and parse PowerShell snippets without executing them. #>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$files = @((Get-Item -LiteralPath (Join-Path $root 'README.md')))
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Filter '*.md' -File -Recurse)
$count = 0
foreach ($file in $files) {
    $source = [IO.File]::ReadAllText($file.FullName)
    $blocks = [regex]::Matches($source, '(?ms)^```powershell[^\r\n]*\r?\n(.*?)^```[ \t]*\r?$')
    foreach ($block in $blocks) {
        $tokens = $null
        $parseErrors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseInput($block.Groups[1].Value, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) {
            throw ('PowerShell documentation syntax error in ' + $file.Name + ': ' + ($parseErrors.Message -join '; '))
        }
        $count++
    }
}
Write-Host ('PASS: parsed ' + $count + ' PowerShell documentation blocks; no snippet executed')
