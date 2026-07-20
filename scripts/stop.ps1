$ErrorActionPreference = "SilentlyContinue"
$Connections = Get-NetTCPConnection -LocalPort 8765 -State Listen
foreach ($Connection in $Connections) {
    Stop-Process -Id $Connection.OwningProcess -Force
}

