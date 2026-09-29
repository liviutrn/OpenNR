[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '2.14.1',
    [string]$AioSource,
    [string]$NeuralRuntimePath,
    [string]$StreamlineRuntimeSource,
    [string]$OutputRoot,
    [string]$ImGuiVRHelperPath,
    [switch]$Force
)

& (Join-Path $PSScriptRoot 'Package-OpenShadersDLSSNRPair.ps1') @PSBoundParameters
