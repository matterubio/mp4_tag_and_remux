# PowerShell example: remux and tag using the Python helper
# Usage: .\remux_tag.ps1 -Input in.mp4 -Output out.mp4

param(
    [Parameter(Mandatory=$true)] [string] $Input,
    [Parameter(Mandatory=$true)] [string] $Output,
    [string[]] $Tag,
    [string[]] $Lang,
    [switch] $DryRun
)

$python = "python"
$script = Join-Path -Path $PSScriptRoot -ChildPath "mp4_tag_remux.py"

$argList = @($Input, $Output)
foreach ($t in $Tag) { $argList += "--tag"; $argList += $t }
foreach ($l in $Lang) { $argList += "--lang"; $argList += $l }
if ($DryRun) { $argList += "--dry-run" }

Write-Host "Running: $python $script $($argList -join ' ')"
& $python $script @argList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
