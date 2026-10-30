param([string]$SkillRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$version = (Get-Content -LiteralPath (Join-Path $SkillRoot 'VERSION') -Raw).Trim()
$base = if ($env:MEDIA_EDITOR_COMPONENT_BASE_URL) {$env:MEDIA_EDITOR_COMPONENT_BASE_URL} else {"https://github.com/Jianxmm/media-editor/releases/download/v$version"}
$cache = if ($env:MEDIA_EDITOR_RUNTIME_CACHE) {$env:MEDIA_EDITOR_RUNTIME_CACHE} else {Join-Path $env:LOCALAPPDATA 'media-editor'}
$work = Join-Path $cache ('.bootstrap-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    $catalogPath = Join-Path $work 'catalog.json'
    $savedCatalog = Join-Path $cache "catalogs/$version/windows-x64.json"
    if (Test-Path -LiteralPath $savedCatalog) {Copy-Item -LiteralPath $savedCatalog -Destination $catalogPath} else {
        Invoke-WebRequest -UseBasicParsing -Uri "$base/components-windows-x64.json" -OutFile $catalogPath
    }
    $catalog = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($catalog.target -ne 'windows-x64' -or $catalog.version -ne $version -or $catalog.runtime.name -ne 'media-editor-runtime-windows-x64.zip') {throw '组件系统或版本不匹配'}
    if ($catalog.runtime.sha256 -notmatch '^[0-9a-f]{64}$') {throw '程序组件哈希无效'}
    $source = Join-Path $cache "programs/$($catalog.runtime.sha256)/media-editor"
    if (-not (Test-Path -LiteralPath (Join-Path $source 'runtime/python/python.exe'))) {
        $archive = Join-Path $work 'runtime.zip'
        Invoke-WebRequest -UseBasicParsing -Uri "$base/$($catalog.runtime.name)" -OutFile $archive
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() -ne $catalog.runtime.sha256) {throw '程序组件校验失败'}
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $work 'program')
        $source = Join-Path $work 'program/media-editor'
    }
    $python = Join-Path $source 'runtime/python/python.exe'
    $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'
    & $python -B (Join-Path $SkillRoot 'scripts/manage_runtime.py') --catalog $catalogPath --cache $cache --base-url $base --runtime-source $source
    if ($LASTEXITCODE -ne 0) {throw '环境准备失败；原环境未切换'}
} finally {Remove-Item -LiteralPath $work -Recurse -Force}
