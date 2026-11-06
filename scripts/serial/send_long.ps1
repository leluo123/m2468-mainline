$ErrorActionPreference = "Stop"
$b64 = $args[0]
$secs = if ($args.Length -gt 1) { [int]$args[1] } else { 75 }
$sp = New-Object System.IO.Ports.SerialPort("COM16", 115200, 'None', 8, 'One')
$sp.ReadTimeout = 5000
try {
    $sp.Open()
    Start-Sleep -Milliseconds 400
    $sp.DiscardInBuffer()
    $sp.Write([char]3); Start-Sleep -Milliseconds 200
    $sp.Write("`r");   Start-Sleep -Milliseconds 800
    $sp.DiscardInBuffer()
    $sp.Write("echo '$b64' | base64 -d > /tmp/p.sh; sh /tmp/p.sh`r")
    $r = ""
    $deadline = (Get-Date).AddSeconds($secs)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $r += $sp.ReadExisting()
    }
    Write-Host $r
}
finally {
    if ($sp.IsOpen) { $sp.Close() }
    $sp.Dispose()
}
