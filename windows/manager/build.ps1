param(
    [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    [string]$Node = (Get-Command node.exe -ErrorAction Stop).Source
)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
if (-not (Test-Path -LiteralPath $Python)) {
    throw '请先创建本项目 .venv 并安装 requirements-build.txt，或通过 -Python 指定构建解释器。'
}
Push-Location $project
try {
    & npm.cmd --prefix resources ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node 依赖安装失败' }
    & $Python make_icon.py
    if ($LASTEXITCODE -ne 0) { throw '图标生成失败' }
    & $Python -m PyInstaller --noconfirm --onedir --windowed --noupx `
        --name ClaudeConnectionManager --icon resources\app.ico `
        --add-data 'ui;ui' --add-data 'resources\guard.cjs;resources' `
        --add-data 'resources\node_modules;resources\node_modules' `
        --add-binary "$Node;runtime" --collect-all webview --collect-all winpty `
        --copy-metadata pystray --copy-metadata pywebview --copy-metadata Pillow `
        --distpath dist --workpath build app.pyw
    if ($LASTEXITCODE -ne 0) { throw 'Windows 应用构建失败' }
    Copy-Item -LiteralPath deployment.example.json -Destination dist\ClaudeConnectionManager\deployment.json -Force
    Copy-Item -LiteralPath README.md -Destination dist\ClaudeConnectionManager\README.md -Force
    Copy-Item -LiteralPath THIRD_PARTY_NOTICES.md -Destination dist\ClaudeConnectionManager\THIRD_PARTY_NOTICES.md -Force
    Copy-Item -LiteralPath resources\Node-LICENSE.txt -Destination dist\ClaudeConnectionManager\Node-LICENSE.txt -Force
} finally { Pop-Location }
