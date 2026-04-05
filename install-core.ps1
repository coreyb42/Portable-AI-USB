# ================================================================
# PORTABLE UNCENSORED AI - AUTOMATED USB SETUP SCRIPT
# ================================================================
# This script downloads and configures everything needed to run
# a fully private, portable AI from a USB drive.
# ================================================================

$USB_Drive = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModelName = "gemma4:e4b"

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Starting Automated Portable AI USB Setup!              " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------------
# STEP 1: Create folder structure
# -----------------------------------------------------------------
Write-Host "[1/4] Creating folders on USB drive..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "$USB_Drive\ollama" | Out-Null
New-Item -ItemType Directory -Force -Path "$USB_Drive\anythingllm" | Out-Null
New-Item -ItemType Directory -Force -Path "$USB_Drive\anythingllm_data\anythingllm-desktop" | Out-Null
New-Item -ItemType Directory -Force -Path "$USB_Drive\logs" | Out-Null
Write-Host "      Done." -ForegroundColor Green

# -----------------------------------------------------------------
# STEP 2: Download Ollama (the AI engine)
# -----------------------------------------------------------------
Write-Host ""
Write-Host "[2/4] Downloading Ollama AI Engine..." -ForegroundColor Yellow
$OllamaURL = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
$OllamaDest = "$USB_Drive\ollama\ollama-windows-amd64.zip"
if (Test-Path "$USB_Drive\ollama\ollama.exe") {
    Write-Host "      Ollama already installed! Skipping..." -ForegroundColor Green
} else {
    curl.exe -L --ssl-no-revoke --progress-bar $OllamaURL -o $OllamaDest
    Write-Host "      Extracting Ollama..." -ForegroundColor Yellow
    Expand-Archive -Path $OllamaDest -DestinationPath "$USB_Drive\ollama" -Force
    Remove-Item $OllamaDest -Force
    Write-Host "      Ollama Setup Complete!" -ForegroundColor Green
}

# -----------------------------------------------------------------
# STEP 3: Download AnythingLLM (the chat interface)
# -----------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Downloading AnythingLLM Chat Interface..." -ForegroundColor Yellow
$AnythingLLMURL = "https://cdn.anythingllm.com/latest/AnythingLLMDesktop.exe"
$InstallerDest = "$USB_Drive\anythingllm\AnythingLLMDesktop.exe"

# Check if we already extracted AnythingLLM previously
if (Test-Path "$USB_Drive\anythingllm\AnythingLLM.exe") {
    Write-Host "      AnythingLLM already set up! Skipping..." -ForegroundColor Green
} else {
    # Download the installer
    if (-Not (Test-Path $InstallerDest) -or (Get-Item $InstallerDest).length -lt 10000000) {
        Write-Host "      Downloading installer..." -ForegroundColor Magenta
        curl.exe -L --ssl-no-revoke --progress-bar $AnythingLLMURL -o $InstallerDest
    }
    
    # Silently extract it directly onto the USB (no install popup!)
    Write-Host "      Extracting AnythingLLM to USB (this takes 1-2 minutes)..." -ForegroundColor Magenta
    
    # Use the 8.3 short path to avoid issues with spaces in folder names
    $ShortPath = (New-Object -ComObject Scripting.FileSystemObject).GetFolder($USB_Drive).ShortPath
    $ExtractDir = "$ShortPath\anythingllm"
    
    Start-Process -FilePath $InstallerDest -ArgumentList "/S /D=$ExtractDir" -Wait
    
    # Clean up the installer to save space
    if (Test-Path "$USB_Drive\anythingllm\AnythingLLM.exe") {
        Remove-Item $InstallerDest -Force -ErrorAction SilentlyContinue
        Write-Host "      AnythingLLM extracted and ready!" -ForegroundColor Green
    } else {
        Write-Host "      AnythingLLM installer downloaded. It will be extracted on first launch." -ForegroundColor Yellow
    }
}

# -----------------------------------------------------------------
# IMPORT MODEL INTO OLLAMA ENGINE
# -----------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Pulling $ModelName into the portable Ollama store..." -ForegroundColor Yellow
$env:OLLAMA_MODELS = "$USB_Drive\ollama\data"
New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null

$existingModels = & "$USB_Drive\ollama\ollama.exe" list 2>&1
if ($existingModels -match [regex]::Escape($ModelName)) {
    Write-Host "      Model already imported! Skipping..." -ForegroundColor Green
} else {
    Write-Host "      Starting Ollama temporarily to download the model..." -ForegroundColor DarkGray
    $ServerProcess = Start-Process -FilePath "$USB_Drive\ollama\ollama.exe" -ArgumentList "serve" -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 5
    & "$USB_Drive\ollama\ollama.exe" pull $ModelName
    Write-Host "      Stopping temporary Ollama server..." -ForegroundColor DarkGray
    Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "      Model imported successfully!" -ForegroundColor Green
}

# -----------------------------------------------------------------
# ALL DONE!
# -----------------------------------------------------------------
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   SETUP COMPLETE! YOUR PORTABLE AI IS READY!             " -ForegroundColor Green 
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  To start your AI: Double-click start-windows.bat" -ForegroundColor White
Write-Host "  On a Mac: Double-click start-mac.command" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to close this installer..." -ForegroundColor Yellow
$Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") | Out-Null
