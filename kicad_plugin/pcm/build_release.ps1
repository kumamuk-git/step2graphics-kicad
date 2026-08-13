[CmdletBinding()]
param(
    [string]$RepositoryBaseUrl = ''
)

$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'build_pcm_package.ps1')
& (Join-Path $PSScriptRoot 'build_repository.ps1') -RepositoryBaseUrl $RepositoryBaseUrl
