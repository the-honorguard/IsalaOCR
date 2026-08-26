param([int]$PollSeconds=2)
$ErrorActionPreference="Stop"
. (Join-Path $PSScriptRoot "training-common.ps1")
$JobsRoot=Join-Path $ProjectRoot "training\workspace\webui\jobs"
foreach($name in @("pending","running","completed","failed","cancelled","cancel","status","logs")){New-Item -ItemType Directory -Force -Path (Join-Path $JobsRoot $name)|Out-Null}
$lock=Join-Path $JobsRoot "worker.json"
$WorkerVersion=(Get-Content (Join-Path $ProjectRoot "project\VERSION") -Raw).Trim()

function Set-JobProperty {
    param([Parameter(Mandatory=$true)]$Object,[Parameter(Mandatory=$true)][string]$Name,$Value)
    if ($null -eq $Object) { throw "Cannot set job property '$Name' on a null object." }
    $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value -Force
}

function Write-JsonUtf8NoBom {
    param([Parameter(Mandatory=$true)]$Value,[Parameter(Mandatory=$true)][string]$Path,[int]$Depth=8)
    $json=$Value | ConvertTo-Json -Depth $Depth
    $encoding=New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path,$json,$encoding)
}

function Add-WorkerLog {
    param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)][string]$Message)
    $encoding=New-Object System.Text.UTF8Encoding($false)
    $line="[{0}] {1}{2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"),$Message,[Environment]::NewLine
    [System.IO.File]::AppendAllText($Path,$line,$encoding)
}

function Get-LiveProgressLabel {
    param([Parameter(Mandatory=$true)][string]$StdoutPath,[Parameter(Mandatory=$true)][string]$StderrPath)
    $paths=@($StdoutPath,$StderrPath) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    if($paths.Count -eq 0){ return "Wachten op eerste scriptuitvoer" }
    try {
        $ordered=@($paths | Sort-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc } -Descending)
        foreach($path in $ordered){
            $lines=@(Get-Content -LiteralPath $path -Tail 180 -ErrorAction SilentlyContinue)
            for($i=$lines.Count-1;$i -ge 0;$i--){
                $line=([string]$lines[$i]).Trim()
                if([string]::IsNullOrWhiteSpace($line)){ continue }
                if($line -match '^#\d+\s+sha256:[0-9a-f]+\s+(?<done>[0-9.]+(?:kB|MB|GB))\s+/\s+(?<total>[0-9.]+(?:kB|MB|GB))'){
                    return ("Docker download · {0} / {1} (huidige laag)" -f $Matches.done,$Matches.total)
                }
                if($line -match '^#\d+\s+\[[^\]]*?\s(?<step>\d+)/(?<total>\d+)\]'){
                    return ("Docker build - stap {0}/{1}" -f $Matches.step,$Matches.total)
                }
                if($line -match '^\[(?<step>\d+)/(?<total>\d+)\]\s*(?<detail>.+)$'){
                    $detail=([string]$Matches.detail).Trim()
                    if($detail.Length -gt 90){ $detail=$detail.Substring(0,87)+"..." }
                    return ("Stap {0}/{1} · {2}" -f $Matches.step,$Matches.total,$detail)
                }
            }
        }
        return "Taak wordt uitgevoerd · live uitvoer actief"
    } catch { return "Taak wordt uitgevoerd · live uitvoer actief" }
}

function Test-IsalaWorkerState {
    param($State,[int]$MaxHeartbeatAgeSeconds=15,[switch]$RequireCurrentVersion)
    if ($null -eq $State -or $null -eq $State.pid -or $null -eq $State.heartbeat_at) { return $false }
    try {
        $pidValue=[int]$State.pid
        $process=Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -eq $process -or $process.ProcessName -notin @('powershell','pwsh')) { return $false }
        $heartbeat=[datetimeoffset]::Parse([string]$State.heartbeat_at)
        if ((([datetimeoffset]::Now)-$heartbeat).TotalSeconds -gt $MaxHeartbeatAgeSeconds) { return $false }
        $cim=Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue" -ErrorAction SilentlyContinue
        if ($null -eq $cim -or [string]$cim.CommandLine -notmatch '(?i)webui-worker\.ps1') { return $false }
        if ($RequireCurrentVersion -and [string]$State.worker_version -ne $WorkerVersion) { return $false }
        return $true
    } catch { return $false }
}

function Stop-IsalaProcessTree {
    param([Parameter(Mandatory=$true)][int]$ProcessId)
    try { & taskkill.exe /PID $ProcessId /T /F *> $null }
    catch { Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue }
}

function Set-WorkerState {
    param([string]$State="idle",[string]$CurrentJobId="")
    $payload=@{pid=$PID;worker_version=$WorkerVersion;state=$State;current_job_id=$CurrentJobId;started_at=$script:WorkerStartedAt;heartbeat_at=(Get-Date).ToString("o")}
    $temp=$lock+".tmp"
    Write-JsonUtf8NoBom -Value $payload -Path $temp -Depth 4
    Move-Item $temp $lock -Force
}

function Complete-InterruptedJobs {
    $runningRoot=Join-Path $JobsRoot "running"
    foreach($runningJob in @(Get-ChildItem $runningRoot -Filter "*.json" -File -ErrorAction SilentlyContinue)){
        try {
            $data=Get-Content $runningJob.FullName -Raw | ConvertFrom-Json
            $jobId=[string]$data.job_id
            if([string]::IsNullOrWhiteSpace($jobId)){$jobId=$runningJob.BaseName}
            $finished=(Get-Date).ToString("o")
            Set-JobProperty $data "status" "failed"
            Set-JobProperty $data "exit_code" 125
            Set-JobProperty $data "finished_at" $finished
            Set-JobProperty $data "updated_at" $finished
            Set-JobProperty $data "progress_percent" 100
            Set-JobProperty $data "progress_mode" "determinate"
            Set-JobProperty $data "progress_label" "Afgebroken door workerherstart"
            Write-JsonUtf8NoBom -Value $data -Path (Join-Path (Join-Path $JobsRoot "status") ($jobId+".json")) -Depth 6
            Add-WorkerLog -Path (Join-Path (Join-Path $JobsRoot "logs") ($jobId+".worker.log")) -Message "Deze taak was nog actief toen de worker opnieuw werd gestart. De taak is veilig als mislukt gemarkeerd; voer hem opnieuw uit."
            Move-Item $runningJob.FullName (Join-Path (Join-Path $JobsRoot "failed") $runningJob.Name) -Force
            Remove-Item (Join-Path $runningRoot ($jobId+".cmd")) -Force -ErrorAction SilentlyContinue
        } catch { Write-Warning "Kon onderbroken taak $($runningJob.Name) niet herstellen: $($_.Exception.Message)" }
    }
}

if(Test-Path $lock){
    try{
        $old=Get-Content $lock -Raw|ConvertFrom-Json
        if(Test-IsalaWorkerState $old -RequireCurrentVersion){Write-Host "Een gezonde IsalaOCR webworker draait al (PID $($old.pid))." -ForegroundColor Yellow;exit 0}
        if(Test-IsalaWorkerState $old){Write-Host "Een verouderde IsalaOCR-worker wordt gestopt (PID $($old.pid), versie $($old.worker_version))." -ForegroundColor Yellow;Stop-IsalaProcessTree -ProcessId ([int]$old.pid);Start-Sleep -Milliseconds 500}
        else {Write-Host "Verouderde workerstatus verwijderd; de geregistreerde worker is niet meer gezond." -ForegroundColor Yellow}
    }catch{Write-Host "Ongeldige workerstatus verwijderd." -ForegroundColor Yellow}
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}

Complete-InterruptedJobs
$script:WorkerStartedAt=(Get-Date).ToString("o")
Write-Host "IsalaOCR webworker v$WorkerVersion gestart." -ForegroundColor Cyan
Write-Host "Wachtrij: $JobsRoot"
Write-Host "Dit venster blijft open. Taken worden vanuit de webinterface opgepakt."
Set-WorkerState -State "starting"
try { & (Join-Path $PSScriptRoot "preparation-status.ps1") } catch { Write-Warning ("Kon voorbereidingsstatus bij workerstart niet controleren: {0}" -f $_.Exception.Message) }

try{
    while($true){
        Set-WorkerState -State "idle"
        # Use the persisted creation timestamp for FIFO ordering. Sorting only
        # by the filename makes jobs created in the same second depend on the
        # random suffix in job_id.
        $job=Get-ChildItem (Join-Path $JobsRoot "pending") -Filter "*.json" -File |
            ForEach-Object {
                $queued = $null
                try { $queued = Get-Content $_.FullName -Raw | ConvertFrom-Json } catch { }
                [pscustomobject]@{
                    FullName = $_.FullName
                    Name = $_.Name
                    BaseName = $_.BaseName
                    CreatedAt = [string]$queued.created_at
                }
            } |
            Sort-Object @{Expression={ if ([string]::IsNullOrWhiteSpace($_.CreatedAt)) { "9999-12-31T23:59:59.9999999Z" } else { $_.CreatedAt } }}, Name |
            Select-Object -First 1
        if($null -eq $job){Start-Sleep -Seconds $PollSeconds;continue}
        Write-Host "[$(Get-Date -Format HH:mm:ss)] Taak gevonden: $($job.BaseName)" -ForegroundColor Cyan
        $running=Join-Path (Join-Path $JobsRoot "running") $job.Name
        try{Move-Item $job.FullName $running -ErrorAction Stop}catch{continue}
        $data=Get-Content $running -Raw|ConvertFrom-Json
        $statusFile=Join-Path (Join-Path $JobsRoot "status") $job.Name
        $logFile=Join-Path (Join-Path $JobsRoot "logs") ($data.job_id+".log")
        $errorFile=$logFile+".err"
        $workerLogFile=Join-Path (Join-Path $JobsRoot "logs") ($data.job_id+".worker.log")
        $cancelFile=Join-Path (Join-Path $JobsRoot "cancel") ($data.job_id+".json")
        Set-JobProperty $data "status" "running"
        Set-JobProperty $data "started_at" ((Get-Date).ToString("o"))
        Set-JobProperty $data "updated_at" ([string]$data.started_at)
        Set-JobProperty $data "log_file" $logFile
        Set-JobProperty $data "progress_percent" 0
        Set-JobProperty $data "progress_mode" "indeterminate"
        Set-JobProperty $data "progress_label" "PowerShell-taak wordt gestart"
        Write-JsonUtf8NoBom -Value $data -Path $statusFile -Depth 6
        Set-WorkerState -State "running" -CurrentJobId ([string]$data.job_id)
        Remove-Item $workerLogFile -Force -ErrorAction SilentlyContinue
        Add-WorkerLog -Path $workerLogFile -Message "Worker heeft taak $($data.job_id) opgepakt."
        Add-WorkerLog -Path $workerLogFile -Message "Start taak: $($data.action_name)"
        if(-not [string]::IsNullOrWhiteSpace([string]$data.project_id)){Add-WorkerLog -Path $workerLogFile -Message "Project: $($data.project_id)"}
        Write-Host "[$(Get-Date -Format HH:mm:ss)] Start taak: $($data.action_name)"

        $exit=1
        $cancelled=$false
        $wrapperFile=Join-Path (Join-Path $JobsRoot "running") ($data.job_id+".cmd")
        $exitCodeFile=Join-Path (Join-Path $JobsRoot "running") ($data.job_id+".exitcode")
        $proc=$null
        try{
            Remove-Item $logFile,$errorFile,$wrapperFile,$exitCodeFile -Force -ErrorAction SilentlyContinue
            if([string]$data.job_type -eq "artifact_delete"){
                $composePath=Join-Path $ProjectRoot "infrastructure\docker\compose.yaml"
                $safeCompose=$composePath.Replace('"','""')
                $safeJobFile=("/training/workspace/webui/jobs/running/{0}.json" -f [string]$data.job_id).Replace('"','""')
                $powerShellCommand='docker compose -f "{0}" --profile training run --rm --no-deps --entrypoint python dataset-builder /opt/isala-training/artifact_delete_runner.py --job-file "{1}"' -f $safeCompose,$safeJobFile
            } else {
                $launcherPath=Join-Path $PSScriptRoot "launcher.ps1"
                $safeLauncher=$launcherPath.Replace('"','""')
                $safeAction=([string]$data.action_id).Replace('"','""')
                $powerShellCommand='powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" action "{1}"' -f $safeLauncher,$safeAction
                if([string]$data.action_id -in @("20","21","22")){$safeSource=([string]$data.options.source_id).Replace('"','""');if(-not [string]::IsNullOrWhiteSpace($safeSource)){$powerShellCommand += ' "{0}"' -f $safeSource}}
                elseif([string]$data.action_id -eq "2"){$safeTableModel=([string]$data.options.table_model_id).Replace('"','""');if(-not [string]::IsNullOrWhiteSpace($safeTableModel)){$powerShellCommand += ' "{0}"' -f $safeTableModel}}
                elseif([string]$data.action_id -eq "26"){$safeDevice=([string]$data.options.device).Replace('"','""');if(-not [string]::IsNullOrWhiteSpace($safeDevice)){$powerShellCommand += ' "{0}"' -f $safeDevice}}
            }
            $jobProjectId=([string]$data.project_id).Replace('"','')
            $wrapperLines=@('@echo off','setlocal',('set "ISALA_PROJECT_ID={0}"' -f $jobProjectId),$powerShellCommand,'set "ISALA_EXIT=%ERRORLEVEL%"',('>"{0}" echo %ISALA_EXIT%' -f $exitCodeFile.Replace('"','""')),'exit /b %ISALA_EXIT%')
            [System.IO.File]::WriteAllLines($wrapperFile,$wrapperLines,(New-Object System.Text.ASCIIEncoding))
            Add-WorkerLog -Path $workerLogFile -Message "PowerShell-launcher wordt niet-interactief gestart; Docker-uitvoer volgt zodra de taak schrijft."
            $cmdArguments='/d /s /c call "{0}"' -f $wrapperFile.Replace('"','""')
            $proc=Start-Process -FilePath $env:ComSpec -ArgumentList $cmdArguments -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow -RedirectStandardOutput $logFile -RedirectStandardError $errorFile
            Add-WorkerLog -Path $workerLogFile -Message "Onderliggend proces gestart (PID $($proc.Id))."
            while(-not $proc.HasExited){
                Start-Sleep -Seconds 1
                $proc.Refresh()
                if(Test-Path -LiteralPath $cancelFile -PathType Leaf){
                    $cancelled=$true
                    Set-JobProperty $data "progress_label" "Annuleren…"
                    Set-JobProperty $data "updated_at" ((Get-Date).ToString("o"))
                    Write-JsonUtf8NoBom -Value $data -Path $statusFile -Depth 6
                    Add-WorkerLog -Path $workerLogFile -Message "Annulering ontvangen; alleen process-tree PID $($proc.Id) wordt gestopt."
                    Stop-IsalaProcessTree -ProcessId ([int]$proc.Id)
                    break
                }
                Set-JobProperty $data "updated_at" ((Get-Date).ToString("o"))
                Set-JobProperty $data "progress_percent" 0
                Set-JobProperty $data "progress_mode" "indeterminate"
                Set-JobProperty $data "progress_label" (Get-LiveProgressLabel -StdoutPath $logFile -StderrPath $errorFile)
                Write-JsonUtf8NoBom -Value $data -Path $statusFile -Depth 6
                Set-WorkerState -State "running" -CurrentJobId ([string]$data.job_id)
            }
            if($null -ne $proc){$proc.WaitForExit();$proc.Refresh()}
            if($cancelled){$exit=130}
            else {
                $exit=[int]$proc.ExitCode
                if(Test-Path -LiteralPath $exitCodeFile -PathType Leaf){$rawExit=([string](Get-Content -LiteralPath $exitCodeFile -Raw -ErrorAction SilentlyContinue)).Trim();$capturedExit=0;if([int]::TryParse($rawExit,[ref]$capturedExit)){$exit=$capturedExit}}
                if($exit -eq 0){$combinedOutput='';if(Test-Path -LiteralPath $logFile){$combinedOutput += [string](Get-Content -LiteralPath $logFile -Raw -ErrorAction SilentlyContinue)};if(Test-Path -LiteralPath $errorFile){$combinedOutput += "`n" + [string](Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue)};if($combinedOutput -match '(?m)^IsalaOCR failed:\s*$' -or $combinedOutput -match '(?m)^Action failed:\s*$'){$exit=1;Add-WorkerLog -Path $workerLogFile -Message "Fatale launcherfout gevonden in scriptuitvoer; taakstatus gecorrigeerd naar mislukt."}}
            }
        }catch{
            if($null -ne $proc -and -not $proc.HasExited){Stop-IsalaProcessTree -ProcessId ([int]$proc.Id)}
            $_|Out-String|Add-Content $errorFile
            Add-WorkerLog -Path $workerLogFile -Message "Workerfout: $($_.Exception.Message)"
            $exit=1
        }finally{
            Remove-Item $wrapperFile,$exitCodeFile,$cancelFile -Force -ErrorAction SilentlyContinue
        }
        Set-JobProperty $data "exit_code" $exit
        Set-JobProperty $data "finished_at" ((Get-Date).ToString("o"))
        Set-JobProperty $data "updated_at" ([string]$data.finished_at)
        Set-JobProperty $data "progress_percent" 100
        Set-JobProperty $data "progress_mode" "determinate"
        if($cancelled){
            Set-JobProperty $data "status" "cancelled"
            Set-JobProperty $data "progress_label" "Geannuleerd"
            $destination=Join-Path $JobsRoot "cancelled"
            Add-WorkerLog -Path $workerLogFile -Message "Taak geannuleerd op verzoek vanuit de WebUI."
        } elseif($exit -eq 0){
            Set-JobProperty $data "status" "completed"
            Set-JobProperty $data "progress_label" "Voltooid"
            $destination=Join-Path $JobsRoot "completed"
            Add-WorkerLog -Path $workerLogFile -Message "Taak voltooid met exitcode 0."
        } else {
            Set-JobProperty $data "status" "failed"
            Set-JobProperty $data "progress_label" "Mislukt"
            $destination=Join-Path $JobsRoot "failed"
            Add-WorkerLog -Path $workerLogFile -Message "Taak mislukt met exitcode $exit."
        }
        Write-JsonUtf8NoBom -Value $data -Path $statusFile -Depth 6
        Move-Item $running (Join-Path $destination $job.Name) -Force
        if($cancelled){Write-Host "[$(Get-Date -Format HH:mm:ss)] Geannuleerd: $($data.job_id)" -ForegroundColor Yellow}
        elseif($exit -eq 0){Write-Host "[$(Get-Date -Format HH:mm:ss)] Voltooid: $($data.job_id)" -ForegroundColor Green}
        else{Write-Host "[$(Get-Date -Format HH:mm:ss)] Mislukt: $($data.job_id) (exit $exit)" -ForegroundColor Red}
        Set-WorkerState -State "idle"
    }
}finally{Remove-Item $lock -Force -ErrorAction SilentlyContinue}
