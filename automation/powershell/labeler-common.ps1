function Get-LabelerContainerId {
    $result = Invoke-DockerWithTimeout -Arguments @('compose','--profile','training','ps','-a','-q','labeler') -TimeoutSeconds 15
    if ($result.TimedOut -or $result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.StdOut)) {
        return $null
    }
    foreach ($line in ($result.StdOut -split "`r?`n")) {
        if (-not [string]::IsNullOrWhiteSpace($line)) { return $line.Trim() }
    }
    return $null
}

function Get-LabelerContainerInfo {
    param([string]$ContainerId)
    if ([string]::IsNullOrWhiteSpace($ContainerId)) { return $null }

    $result = Invoke-DockerWithTimeout -Arguments @('inspect',$ContainerId) -TimeoutSeconds 15
    if ($result.TimedOut -or $result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.StdOut)) {
        return $null
    }
    try {
        $items = @($result.StdOut | ConvertFrom-Json)
        if ($items.Count -eq 0) { return $null }
        return $items[0]
    }
    catch {
        Write-Warning "Docker returned container information that could not be parsed as JSON."
        return $null
    }
}

function Get-LabelerImageBuildInfo {
    param($ContainerInfo)

    $imageName = [string]($ContainerInfo.Config.Image)
    if ([string]::IsNullOrWhiteSpace($imageName)) { return $null }
    $result = Invoke-DockerWithTimeout -Arguments @('image', 'inspect', $imageName) -TimeoutSeconds 15
    if ($result.TimedOut -or $result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.StdOut)) {
        return $null
    }
    try {
        $items = @($result.StdOut | ConvertFrom-Json)
        if ($items.Count -eq 0 -or [string]::IsNullOrWhiteSpace([string]$items[0].Created)) { return $null }
        $created = [DateTimeOffset]::Parse([string]$items[0].Created).ToLocalTime()
        return [pscustomobject]@{
            Image = $imageName
            Created = $created
            Display = $created.ToString('yyyy-MM-dd HH:mm:ss')
        }
    }
    catch {
        return $null
    }
}

function Remove-LabelerContainer {
    param([string]$ContainerId)
    if ([string]::IsNullOrWhiteSpace($ContainerId)) { return $false }

    $result = Invoke-DockerWithTimeout -Arguments @('rm','--force',$ContainerId) -TimeoutSeconds 30
    if ($result.TimedOut) {
        throw "Timed out while removing the previous labeler container. Restart Docker Desktop."
    }
    if ($result.ExitCode -eq 0) { return $true }

    $message = Get-IsalaProcessOutputText -Result $result -Fallback ("Docker returned exit code {0} without additional output." -f $result.ExitCode)
    if ($message -match "No such container") { return $false }
    throw "The previous labeler container could not be removed: $message"
}

function Get-PublishedLabelerPort {
    param($ContainerInfo)

    if ($null -eq $ContainerInfo -or $null -eq $ContainerInfo.NetworkSettings) { return $null }
    $ports = $ContainerInfo.NetworkSettings.Ports
    if ($null -eq $ports) { return $null }

    $property = $ports.PSObject.Properties['8088/tcp']
    if ($null -eq $property -or $null -eq $property.Value) { return $null }

    $bindings = @($property.Value)
    if ($bindings.Count -eq 0 -or $null -eq $bindings[0]) { return $null }

    $hostPort = [string]$bindings[0].HostPort
    $parsed = 0
    if ([int]::TryParse($hostPort, [ref]$parsed)) { return $parsed }
    return $null
}

function Get-StoredLabelerPort {
    param([string]$PortFile)

    if (-not (Test-Path $PortFile)) { return $null }
    try {
        $raw = (Get-Content $PortFile -Raw).Trim()
        $parsed = 0
        if ([int]::TryParse($raw, [ref]$parsed)) { return $parsed }
    }
    catch { }
    return $null
}

function Test-LabelerHealth {
    param([int]$Port)

    if ($Port -le 0) { return $false }
    $request = $null
    $response = $null
    $reader = $null
    try {
        # Startup probes are expected to fail briefly while Docker publishes
        # the port. Use the .NET request API so a refused connection/timeout is
        # caught as a normal exception and never emitted by Invoke-RestMethod
        # into the startup transcript.
        $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/health")
        $request.Method = "GET"
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $response = $request.GetResponse()
        $reader = New-Object IO.StreamReader($response.GetResponseStream())
        $payload = $reader.ReadToEnd() | ConvertFrom-Json
        return ($null -ne $payload -and $payload.ok -eq $true)
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
    }
}

function Test-LocalPortAvailable {
    param([int]$Port)

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        try { $listener.Stop() } catch { }
    }
}

function Get-LabelerStateSummary {
    param($ContainerInfo)

    if ($null -eq $ContainerInfo -or $null -eq $ContainerInfo.State) {
        return [pscustomobject]@{
            Status = 'missing'
            Health = 'none'
            ExitCode = $null
        }
    }

    $health = 'none'
    if ($null -ne $ContainerInfo.State.Health -and
        -not [string]::IsNullOrWhiteSpace([string]$ContainerInfo.State.Health.Status)) {
        $health = [string]$ContainerInfo.State.Health.Status
    }

    return [pscustomobject]@{
        Status = [string]$ContainerInfo.State.Status
        Health = $health
        ExitCode = $ContainerInfo.State.ExitCode
    }
}

function Show-LabelerDiagnostics {
    param(
        [string]$ContainerId,
        [int]$Port = 0
    )

    Write-Host ""
    Write-Host "Docker Compose status:" -ForegroundColor Yellow
    $status = Invoke-DockerWithTimeout -Arguments @('compose','--profile','training','ps','-a','labeler') -TimeoutSeconds 15
    if ($status.TimedOut) { Write-Host "Docker status timed out." -ForegroundColor Red }
    else { Write-NativeProcessResult -Result $status -IncludeEmpty }

    if (-not [string]::IsNullOrWhiteSpace($ContainerId)) {
        $info = Get-LabelerContainerInfo -ContainerId $ContainerId
        if ($null -ne $info) {
            $summary = Get-LabelerStateSummary -ContainerInfo $info
            Write-Host ""
            Write-Host "Container state:" -ForegroundColor Yellow
            Write-Host "Status:    $($summary.Status)"
            Write-Host "Health:    $($summary.Health)"
            Write-Host "Exit code: $($summary.ExitCode)"
            $publishedPort = Get-PublishedLabelerPort -ContainerInfo $info
            if ($null -ne $publishedPort) {
                Write-Host "Published: 127.0.0.1:$publishedPort -> container 8088"
            }
        }
    }

    Write-Host ""
    Write-Host "Recent labeler logs:" -ForegroundColor Yellow
    $logs = Invoke-DockerWithTimeout -Arguments @('compose','--profile','training','logs','--tail','200','labeler') -TimeoutSeconds 20
    if ($logs.TimedOut) { Write-Host "Docker logs timed out." -ForegroundColor Red }
    else { Write-NativeProcessResult -Result $logs -IncludeEmpty }

    if ($Port -gt 0) {
        Write-Host ""
        Write-Host "Host port check for 127.0.0.1:${Port}:" -ForegroundColor Yellow
        Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Detailed |
            Format-List ComputerName,RemoteAddress,RemotePort,TcpTestSucceeded
        Write-Host "Health URL: http://127.0.0.1:$Port/health"
    }
}
