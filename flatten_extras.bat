@echo off
rem flatten_extras.bat
rem Usage: flatten_extras.bat <input-dir>
rem Walks every directory under <input-dir>; if a directory contains an "extras" subfolder,
rem moves all files from nested subfolders of that "extras" up into the extras root.
rem Uses PowerShell for safe recursive file handling and collision-avoidance.

setlocal
if "%~1"=="" (
  set "INPUT=%CD%"
) else (
  set "INPUT=%~1"
)

if not exist "%INPUT%" (
  echo Input directory "%INPUT%" not found.
  exit /b 1
)

echo Scanning directories under "%INPUT%" ...

set "WHATIFARG="
if "%~2"=="--whatif" (
  set "WHATIFARG=-WhatIf"
)

rem Use the PowerShell helper script for robust behavior
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0flatten_extras.ps1" "%INPUT%" %WHATIFARG%

echo Done.
endlocal
