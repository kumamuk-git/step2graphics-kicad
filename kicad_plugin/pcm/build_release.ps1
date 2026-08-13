[CmdletBinding()]
param(
    [string]$RepositoryBaseUrl = 'https://raw.githubusercontent.com/kumamuk-git/step2graphics-kicad/main'
)

$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'build_pcm_package.ps1')
& (Join-Path $PSScriptRoot 'build_repository.ps1') -RepositoryBaseUrl $RepositoryBaseUrl
