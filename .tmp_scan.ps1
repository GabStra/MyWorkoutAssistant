Get-PhysicalDisk | Format-Table FriendlyName, MediaType, BusType, @{n='SizeGB';e={[math]::Round($_.Size/1GB)}}, SpindleSpeed -AutoSize
Write-Output "=== Partition -> Disk mapping ==="
Get-Partition | Where-Object DriveLetter | ForEach-Object {
    $d = Get-Disk -Number $_.DiskNumber
    '{0}:  disk {1}  ({2}, {3}, {4} GB)' -f $_.DriveLetter, $_.DiskNumber, $d.FriendlyName, $d.BusType, [math]::Round($d.Size/1GB)
}
