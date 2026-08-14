[CmdletBinding()]
param(
    [string]$RepositoryBaseUrl = '',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
}
elseif (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
}

$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$metadataPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'metadata.json')).Path
$metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = $metadata.versions[0]
if ([string]::IsNullOrWhiteSpace($RepositoryBaseUrl)) {
    $RepositoryBaseUrl = (
        'https://raw.githubusercontent.com/kumamuk-git/step2graphics-kicad/v' +
        $version.version
    )
}
$archiveName = "step2graphics-kicad10-action-plugin-$($version.version).zip"
$archivePath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "dist\$archiveName")).Path
$archive = Get-Item -LiteralPath $archivePath
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $installSize = ($zip.Entries | Measure-Object -Property Length -Sum).Sum
}
finally {
    $zip.Dispose()
}

$version | Add-Member -NotePropertyName download_url -NotePropertyValue (
    "$RepositoryBaseUrl/kicad_plugin/pcm/dist/$archiveName"
) -Force
$version | Add-Member -NotePropertyName download_sha256 -NotePropertyValue $archiveHash -Force
$version | Add-Member -NotePropertyName download_size -NotePropertyValue ([long]$archive.Length) -Force
$version | Add-Member -NotePropertyName install_size -NotePropertyValue ([long]$installSize) -Force

$packagesPath = Join-Path $outputRoot 'packages.json'
$packagesDocument = [ordered]@{
    packages = @($metadata)
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$packagesJson = ($packagesDocument | ConvertTo-Json -Depth 20) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($packagesPath, $packagesJson + "`n", $utf8NoBom)

$packagesHash = (Get-FileHash -LiteralPath $packagesPath -Algorithm SHA256).Hash.ToLowerInvariant()
$now = [DateTimeOffset]::UtcNow
$repositoryDocument = [ordered]@{
    '$schema' = 'https://go.kicad.org/pcm/schemas/v2#/definitions/Repository'
    name = 'STEP Projection Importer Repository'
    schema_version = 2
    maintainer = [ordered]@{
        name = $metadata.author.name
        contact = $metadata.author.contact
    }
    packages = [ordered]@{
        url = "$RepositoryBaseUrl/packages.json"
        sha256 = $packagesHash
        update_timestamp = $now.ToUnixTimeSeconds()
        update_time_utc = $now.UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss')
    }
}
$repositoryPath = Join-Path $outputRoot 'repository.json'
$repositoryJson = ($repositoryDocument | ConvertTo-Json -Depth 20) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($repositoryPath, $repositoryJson + "`n", $utf8NoBom)

[PSCustomObject]@{
    Repository = $repositoryPath
    Packages = $packagesPath
    Package = $archivePath
    PackageSHA256 = $archiveHash
    PackageSize = $archive.Length
    InstallSize = $installSize
}
