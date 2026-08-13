[CmdletBinding()]
param(
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $PSScriptRoot 'dist'
}

$pluginRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pluginSource = Join-Path $pluginRoot 'plugin'
$metadataPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'metadata.json')).Path
$metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = $metadata.versions[0].version

$entries = @(
    @{ Source = (Join-Path $pluginSource '__init__.py'); Archive = 'plugins/__init__.py' },
    @{ Source = (Join-Path $pluginSource 'step2graphics.py'); Archive = 'plugins/step2graphics.py' },
    @{ Source = (Join-Path $pluginSource 'projection_worker.py'); Archive = 'plugins/projection_worker.py' },
    @{ Source = (Join-Path $pluginSource 'local_projection.py'); Archive = 'plugins/local_projection.py' },
    @{ Source = (Join-Path $pluginSource 'projection_geometry.py'); Archive = 'plugins/projection_geometry.py' }
)

foreach ($entry in $entries) {
    if (-not (Test-Path -LiteralPath $entry.Source -PathType Leaf)) {
        throw "Required plugin file is missing: $($entry.Source)"
    }
}

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

$resolvedOutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$outputPath = Join-Path $resolvedOutputDirectory "step2graphics-kicad10-action-plugin-$version.zip"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$stream = [System.IO.File]::Open(
    $outputPath,
    [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::None
)

try {
    $archive = New-Object System.IO.Compression.ZipArchive(
        $stream,
        [System.IO.Compression.ZipArchiveMode]::Create,
        $false
    )
    try {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $metadataPath,
            'metadata.json',
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
        foreach ($entry in $entries) {
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $entry.Source,
                $entry.Archive,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    $stream.Dispose()
}

$file = Get-Item -LiteralPath $outputPath
$hash = Get-FileHash -LiteralPath $outputPath -Algorithm SHA256
[PSCustomObject]@{
    Package = $file.FullName
    Size = $file.Length
    SHA256 = $hash.Hash.ToLowerInvariant()
}
