param([int]$count = 1)
$sp = New-Object System.IO.Ports.SerialPort('COM16',115200,'None',8,'One')
$sp.ReadTimeout = 300
$sp.Open()
Start-Sleep -Milliseconds 300
for ($i=0; $i -lt $count; $i++) {
    $sp.Write([string][char]3)
    Start-Sleep -Milliseconds 250
}
Start-Sleep -Milliseconds 800
$r = ""
try { $r = $sp.ReadExisting() } catch {}
$sp.Close()
Write-Output "--- AFTER CTRL-C ---"
Write-Output $r
