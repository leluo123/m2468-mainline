param([string]$Cmd = "reboot bootloader", [int]$Secs = 8)
$ErrorActionPreference = "Stop"
try {
    $sp = New-Object System.IO.Ports.SerialPort('COM16',115200,'None',8,'One')
    $sp.ReadTimeout = 500
    $sp.WriteTimeout = 1000
    $sp.Open()
    Start-Sleep -Milliseconds 300
    $sp.DiscardInBuffer()
    $sp.Write($Cmd + "`r")
    Start-Sleep -Seconds 2
    # 补一个回车，防止首个 CR 被 shell 吞掉
    $sp.Write("`r")
    $end = (Get-Date).AddSeconds($Secs)
    $out = ""
    while ((Get-Date) -lt $end) {
        try { $out += $sp.ReadExisting() } catch {}
        Start-Sleep -Milliseconds 200
    }
    $sp.Close()
    Write-Output "=== SENT: $Cmd ==="
    Write-Output $out
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
    exit 1
}
