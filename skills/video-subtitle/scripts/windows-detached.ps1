# windows-detached.ps1
#
# Template for launching a long-running job (whisperX transcription, ffmpeg
# burn) detached on Windows so it survives shell timeouts (~10 min in some
# agent environments). PowerShell's Start-Process is the reliable form — the
# `start /b` bat trick breaks under Git Bash path translation and the child
# doesn't always detach cleanly from the parent shell.
#
# Fill in the four variables, then run:
#     powershell -ExecutionPolicy Bypass -File windows-detached.ps1
# The launch returns immediately. Monitor with `Get-Process python` / the log.

# ---- fill these in ----
$Python      = "C:\path\to\.venv\Scripts\python.exe"
$Script      = "C:\path\to\video-subtitle-skill\skills\video-subtitle\scripts\transcribe.py"
$Args        = @(
    "transcript/input.audio.wav",
    "transcript/input.en.srt",
    "large-v3",
    "float32"
)
$LogFile     = "C:\path\to\per-video-dir\transcript\transcribe.log"
$ErrLogFile  = "C:\path\to\per-video-dir\transcript\transcribe.err.log"
$WorkDir     = "C:\path\to\per-video-dir"
# -----------------------

Start-Process -FilePath $Python `
              -ArgumentList (@($Script) + $Args) `
              -WorkingDirectory $WorkDir `
              -RedirectStandardOutput $LogFile `
              -RedirectStandardError $ErrLogFile `
              -WindowStyle Hidden

# Give it a moment, then confirm it's alive and writing.
Start-Sleep -Seconds 15
$proc = Get-Process -Name python -ErrorAction SilentlyContinue
if ($proc) {
    $size = if (Test-Path $LogFile) { (Get-Item $LogFile).Length } else { 0 }
    Write-Host "detached OK: PID $($proc.Id -join ', '), log $size bytes"
} else {
    Write-Host "WARN: no python process after 15s — check $ErrLogFile"
}
