#requires -Version 5.1
<# Offline contract tests. All fixture data lives under one new TEMP directory. #>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$exporter = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools\export-windows-source.ps1'
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('ccen-export-test-' + [Guid]::NewGuid().ToString('N'))
$script:checks = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
    $script:checks++
}

function Write-Fixture([string]$Root, [string]$Relative, [string]$Content) {
    $path = Join-Path $Root $Relative
    $parent = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    [IO.File]::WriteAllText($path, $Content, (New-Object Text.UTF8Encoding $false))
}

function Invoke-ExpectedFailure([scriptblock]$Action) {
    $messages = New-Object 'System.Collections.Generic.List[string]'
    $failed = $false
    try {
        & $Action *>&1 | ForEach-Object { $messages.Add($_.ToString()) }
    }
    catch {
        $failed = $true
        $messages.Add($_.Exception.Message)
    }
    Assert-True $failed 'operation must fail'
    return ($messages -join "`n")
}

function Get-FixtureSnapshot([string]$Root) {
    # Source snapshot has no junctions when this function is called.
    return ((Get-ChildItem -LiteralPath $Root -File -Recurse -Force |
        Sort-Object FullName |
        ForEach-Object {
            $_.FullName.Substring($Root.Length + 1) + ':' +
                (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }) -join "`n")
}

try {
    New-Item -ItemType Directory -Path $scratch | Out-Null
    $source = Join-Path $scratch 'source project'
    $normalExport = Join-Path $scratch 'normal export'
    New-Item -ItemType Directory -Path $source | Out-Null

    $expectedPaths = @(
        'app.pyw', 'resources\guard.cjs', 'src\space dir\helper.py',
        'build.ps1', 'requirements.txt', 'requirements-dev.txt', 'assets\icon.svg'
    )
    Write-Fixture $source 'app.pyw' "print('offline fixture')"
    Write-Fixture $source 'resources\guard.cjs' '// offline fixture; no network requests'
    Write-Fixture $source 'src\space dir\helper.py' 'value = 1'
    Write-Fixture $source 'build.ps1' "Write-Host 'offline fixture'"
    Write-Fixture $source 'requirements.txt' '# empty offline fixture'
    Write-Fixture $source 'requirements-dev.txt' '# empty offline fixture'
    Write-Fixture $source 'assets\icon.svg' '<svg xmlns="http://www.w3.org/2000/svg" />'

    $excludedPaths = @(
        '.git\hidden.py', 'node_modules\vendor.js', '.venv\runtime.py',
        '__pycache__\cached.py', 'build\generated.py', 'dist\bundled.js',
        '_internal\runtime.py', 'logs\trace.py', 'state\state.py',
        'profiles\profile.py', 'config\settings.py', 'configs\settings.py',
        'secrets\settings.py', 'backups\saved.py', '.vscode\task.js',
        'runtime.json', 'package.json', '.env', 'session.py', 'credentials.py',
        'app.exe', 'module.pyc'
    )
    foreach ($relative in $excludedPaths) {
        Write-Fixture $source $relative 'excluded offline fixture'
    }
    $before = Get-FixtureSnapshot $source
    & $exporter -SourceRoot $source -DestinationRoot $normalExport *>&1 | Out-Null
    Assert-True (Test-Path -LiteralPath (Join-Path $normalExport 'PRIVATE-READ-BEFORE-SHARING.txt')) 'PRIVATE marker exists'
    Assert-True (Test-Path -LiteralPath (Join-Path $normalExport 'EXPORT-COMPLETE.txt')) 'successful export has completion marker'
    Assert-True ((Get-Content -LiteralPath (Join-Path $normalExport 'PRIVATE-READ-BEFORE-SHARING.txt') -Raw) -match 'PRIVATE') 'marker labels export private'
    $manifest = @(Import-Csv -LiteralPath (Join-Path $normalExport 'SOURCE-MANIFEST.csv'))
    Assert-True ($manifest.Count -eq $expectedPaths.Count) 'manifest includes exactly the allowed fixture files'
    foreach ($relative in $expectedPaths) {
        $copy = Join-Path $normalExport $relative
        Assert-True (Test-Path -LiteralPath $copy -PathType Leaf) ('allowed file copied: ' + $relative)
        $rows = @($manifest | Where-Object { $_.RelativePath -eq $relative })
        Assert-True ($rows.Count -eq 1) ('manifest contains one row: ' + $relative)
        $row = $rows[0]
        Assert-True (-not [IO.Path]::IsPathRooted($row.RelativePath)) 'manifest paths are relative'
        Assert-True (-not ($row.RelativePath -match '(^|[\\/])\.\.([\\/]|$)')) 'manifest paths do not traverse parents'
        $sourceHash = (Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash
        $copiedHash = (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash
        Assert-True ($row.SHA256 -eq $sourceHash -and $row.SHA256 -eq $copiedHash) ('manifest hashes match source and copy: ' + $relative)
        Assert-True ([long]$row.Bytes -eq (Get-Item -LiteralPath $copy).Length) ('manifest size matches copy: ' + $relative)
    }
    foreach ($relative in $excludedPaths) {
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $normalExport $relative))) ('excluded file omitted: ' + $relative)
    }
    $omissions = @(Import-Csv -LiteralPath (Join-Path $normalExport 'EXPORT-OMISSIONS.csv'))
    Assert-True (@($omissions | Where-Object { $_.RelativePath -eq 'package.json' -and $_.Reason -eq 'not-allowlisted' }).Count -eq 1) 'omissions report names an excluded dependency manifest'
    Assert-True (@($omissions | Where-Object { $_.RelativePath -eq 'config' -and $_.Reason -eq 'excluded-directory-not-traversed' }).Count -eq 1) 'omissions report records excluded config directory'
    Assert-True (@($omissions | Where-Object { $_.RelativePath -eq 'config\settings.py' }).Count -eq 0) 'excluded directories are not inventoried recursively'
    Assert-True (@($omissions | Where-Object { $_.RelativePath -eq 'credentials.py' -and $_.Reason -eq 'sensitive-filename' }).Count -eq 1) 'omissions report names sensitive filename reason'
    foreach ($omission in $omissions) {
        Assert-True (-not [IO.Path]::IsPathRooted($omission.RelativePath)) 'omissions paths are relative'
        Assert-True (-not ($omission.RelativePath -match '(^|[\\/])\.\.([\\/]|$)')) 'omissions paths do not traverse parents'
    }
    Assert-True ((Get-FixtureSnapshot $source) -eq $before) 'normal export does not alter source bytes'
    Write-Host 'PASS: allowlist, exclusions, PRIVATE/completion markers, relative inventories, hashes, unchanged source'

    # Resolve relative paths against PowerShell's current location, which need
    # not equal the process working directory used by System.IO by default.
    $relativeExport = Join-Path $scratch 'relative export'
    Push-Location -LiteralPath $source
    try {
        & $exporter -SourceRoot '.' -DestinationRoot '..\relative export' *>&1 | Out-Null
    }
    finally { Pop-Location }
    Assert-True (Test-Path -LiteralPath (Join-Path $relativeExport 'EXPORT-COMPLETE.txt')) 'relative source and destination use PowerShell current location'

    $minimalSource = Join-Path $scratch 'minimal source'
    Write-Fixture $minimalSource 'app.py' 'value = 1'
    $minimalExport = Join-Path $scratch 'minimal export'
    & $exporter -SourceRoot $minimalSource -DestinationRoot $minimalExport *>&1 | Out-Null
    $emptyOmissions = @(Import-Csv -LiteralPath (Join-Path $minimalExport 'EXPORT-OMISSIONS.csv'))
    Assert-True ($emptyOmissions.Count -eq 0) 'omissions CSV has a valid header even with no omissions'
    Assert-True (Test-Path -LiteralPath (Join-Path $minimalExport 'EXPORT-COMPLETE.txt')) 'minimal export completes'
    Write-Host 'PASS: relative path resolution and empty omission inventory'

    $existingExport = Join-Path $scratch 'already exists'
    New-Item -ItemType Directory -Path $existingExport | Out-Null
    Write-Fixture $existingExport 'keep.txt' 'preserve existing contents'
    $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot $source -DestinationRoot $existingExport }
    Assert-True ($messages -match 'already exists') 'existing destination rejection explains conflict'
    Assert-True ((Get-Content -LiteralPath (Join-Path $existingExport 'keep.txt') -Raw) -eq 'preserve existing contents') 'existing destination content preserved'
    Assert-True (@(Get-ChildItem -LiteralPath $existingExport -Force).Count -eq 1) 'existing destination receives no files'

    $nestedExport = Join-Path $source 'nested export'
    $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot $source -DestinationRoot $nestedExport }
    Assert-True (-not (Test-Path -LiteralPath $nestedExport)) 'destination inside source is rejected before writing'
    $missingExport = Join-Path $scratch 'missing source export'
    $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot (Join-Path $scratch 'does not exist') -DestinationRoot $missingExport }
    Assert-True (-not (Test-Path -LiteralPath $missingExport)) 'missing source is rejected before writing'
    Write-Host 'PASS: refuses existing destination, source-nested destination and missing source'

    # Synthesize a test-only credential string. Never print its value.
    $secretValue = 'offline-fixture-' + [Guid]::NewGuid().ToString('N')
    $secretFile = 'src\unsafe.py'
    Write-Fixture $source $secretFile (('proxy_' + 'password = "') + $secretValue + '"')
    $rejectedExport = Join-Path $scratch 'must not exist'
    $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot $source -DestinationRoot $rejectedExport }
    Assert-True (-not (Test-Path -LiteralPath $rejectedExport)) 'credential pre-scan creates no output directory'
    Assert-True ($messages -match 'literal-secret') 'credential pre-scan names the matched rule'
    Assert-True (-not $messages.Contains($secretValue)) 'credential pre-scan does not echo the credential value'
    $literalCases = @(
        [pscustomobject]@{
            Name = 'prefixed API key'
            Content = (('ANTHROPIC_' + 'API_KEY = "') + $secretValue + '"')
            Value = $secretValue
        },
        [pscustomobject]@{
            Name = 'short password'
            Content = (('PASS' + 'WORD = "') + ('a' * 3) + '"')
            Value = ('a' * 3)
        },
        [pscustomobject]@{
            Name = 'annotated Python literal'
            Content = (('proxy_' + 'password: str = "') + $secretValue + '"')
            Value = $secretValue
        },
        [pscustomobject]@{
            Name = 'PowerShell environment key'
            Content = (('$env:ANTHROPIC_' + 'API_KEY = "') + $secretValue + '"')
            Value = $secretValue
        }
    )
    $literalIndex = 0
    foreach ($case in $literalCases) {
        $literalIndex++
        Write-Fixture $source $secretFile $case.Content
        $caseExport = Join-Path $scratch ('literal rejection ' + $literalIndex)
        $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot $source -DestinationRoot $caseExport }
        Assert-True (-not (Test-Path -LiteralPath $caseExport)) ('credential rejected before output: ' + $case.Name)
        Assert-True ($messages -match 'literal-secret') ('credential rule identified: ' + $case.Name)
        Assert-True (-not $messages.Contains($case.Value)) ('credential value not printed: ' + $case.Name)
    }
    Remove-Item -LiteralPath (Join-Path $source $secretFile)
    Assert-True ((Get-FixtureSnapshot $source) -eq $before) 'credential test leaves source fixture unchanged after removing only its synthetic file'
    Write-Host 'PASS: plain, prefixed, short and annotated credential literals rejected without printing values'

    $outside = Join-Path $scratch 'outside project'
    New-Item -ItemType Directory -Path $outside | Out-Null
    Write-Fixture $outside 'private.py' (('proxy_' + 'password = "') + $secretValue + '"')
    $junction = Join-Path $source 'linked outside'
    $junctionCreated = $false
    try {
        New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null
        $junctionCreated = $true
    }
    catch {
        Write-Host 'SKIP: this host cannot create a junction; other security tests still ran'
    }
    if ($junctionCreated) {
        $junctionExport = Join-Path $scratch 'junction export'
        & $exporter -SourceRoot $source -DestinationRoot $junctionExport *>&1 | Out-Null
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $junctionExport 'linked outside'))) 'directory junction omitted'
        $junctionManifest = @(Import-Csv -LiteralPath (Join-Path $junctionExport 'SOURCE-MANIFEST.csv'))
        Assert-True ($junctionManifest.Count -eq $expectedPaths.Count) 'junction target not traversed or included in manifest'
        $junctionOmissions = @(Import-Csv -LiteralPath (Join-Path $junctionExport 'EXPORT-OMISSIONS.csv'))
        Assert-True (@($junctionOmissions | Where-Object { $_.RelativePath -eq 'linked outside' -and $_.Reason -eq 'reparse-point-not-followed' }).Count -eq 1) 'junction omission is inventoried'

        Write-Fixture $outside 'nested source\app.py' 'value = 1'
        $aliasedSourceExport = Join-Path $scratch 'aliased source export'
        $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot (Join-Path $junction 'nested source') -DestinationRoot $aliasedSourceExport }
        Assert-True ($messages -match 'ancestors') 'source with junction ancestor explains rejection'
        Assert-True (-not (Test-Path -LiteralPath $aliasedSourceExport)) 'source with junction ancestor creates no output'

        # The destination alias is outside the source, so lexical containment
        # alone would permit writing through it. Check ancestor rejection.
        $destinationAlias = Join-Path $scratch 'destination alias'
        New-Item -ItemType Junction -Path $destinationAlias -Target $outside | Out-Null
        $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot $source -DestinationRoot (Join-Path $destinationAlias 'redirected export') }
        Assert-True ($messages -match 'ancestors') 'destination with junction ancestor explains rejection'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $outside 'redirected export'))) 'destination junction ancestor cannot redirect export writes'
        Write-Host 'PASS: junction entries not traversed; source and destination junction ancestors rejected'
    }

    $binaryOnly = Join-Path $scratch 'installed build'
    New-Item -ItemType Directory -Path $binaryOnly | Out-Null
    Write-Fixture $binaryOnly 'ClaudeConnectionManager.exe' 'not a real binary'
    Write-Fixture $binaryOnly '_internal\runtime.py' 'excluded fixture'
    $binaryExport = Join-Path $scratch 'binary export'
    $messages = Invoke-ExpectedFailure { & $exporter -SourceRoot $binaryOnly -DestinationRoot $binaryExport }
    Assert-True (-not (Test-Path -LiteralPath $binaryExport)) 'EXE plus _internal rejected without creating export'
    Write-Host ('PASS: installed build is not source; ' + $script:checks + ' assertions passed')
}
finally {
    if (Test-Path -LiteralPath $scratch) {
        # Every path under this unique directory, including the junction target,
        # was created by this test. Nothing outside it is deleted.
        Remove-Item -LiteralPath $scratch -Recurse -Force
    }
}
