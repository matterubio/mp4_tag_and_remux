param(
  [Parameter(Mandatory=$false)]
  [string]$InputDir = '.',
  [switch]$WhatIf
)

Write-Output "Flattening 'extras' folders under: $InputDir"

try {
  $root = Get-Item -LiteralPath $InputDir -ErrorAction Stop
} catch {
  Write-Error "Input directory '$InputDir' not found or inaccessible"
  exit 1
}

# Find all directories that contain an 'extras' subfolder
Get-ChildItem -LiteralPath $root.FullName -Directory -Recurse | ForEach-Object {
  $extrasPath = Join-Path $_.FullName 'extras'
  if (Test-Path -LiteralPath $extrasPath) {
    Write-Output "Processing: $extrasPath"
    $extrasRoot = (Get-Item -LiteralPath $extrasPath).FullName

    # find all files under extras that are not directly in the extras root
    $files = Get-ChildItem -LiteralPath $extrasPath -Recurse -File | Where-Object { $_.DirectoryName -ne $extrasRoot }
    foreach ($f in $files) {
      $src = $f.FullName
      $dest = Join-Path $extrasRoot $f.Name
      $base = $f.BaseName
      $ext = $f.Extension
      $i = 1
      while (Test-Path -LiteralPath $dest) {
        $dest = Join-Path $extrasRoot ("$base-$i$ext")
        $i++
      }
      if ($WhatIf) {
        Write-Output "Would move: $src -> $dest"
      } else {
        try {
          Move-Item -LiteralPath $src -Destination $dest -ErrorAction Stop
          Write-Output "Moved: $src -> $dest"
        } catch {
          Write-Warning "Failed to move $src : $_"
        }
      }
    }

    # Remove now-empty subdirectories under extras (deepest first)
    $dirs = Get-ChildItem -LiteralPath $extrasRoot -Directory -Recurse | Sort-Object -Property FullName -Descending
    foreach ($d in $dirs) {
      $children = Get-ChildItem -LiteralPath $d.FullName -Force -ErrorAction SilentlyContinue
      if (-not $children -or $children.Count -eq 0) {
        if ($WhatIf) {
          Write-Output "Would remove empty dir: $($d.FullName)"
        } else {
          try {
            Remove-Item -LiteralPath $d.FullName -Force -Recurse -ErrorAction Stop
            Write-Output "Removed empty dir: $($d.FullName)"
          } catch {
            Write-Warning "Failed to remove $($d.FullName): $_"
          }
        }
      }
    }
  }
}

Write-Output "Done."
