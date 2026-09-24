Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv-pilot\Scripts\python.exe"
$configPath = Join-Path $env:LOCALAPPDATA "TramCanQR\config.env"
$portableConfigPath = Join-Path $projectRoot "config.env"
$localUrl = "http://127.0.0.1:8080"
$healthUrl = "$localUrl/api/health"

$form = New-Object System.Windows.Forms.Form
$form.Text = "Tram Can QR - Local"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(520, 285)
$form.MinimumSize = New-Object System.Drawing.Size(520, 285)
$form.MaximizeBox = $false
$form.FormBorderStyle = "FixedDialog"
$form.BackColor = [System.Drawing.Color]::White
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)

$title = New-Object System.Windows.Forms.Label
$title.Text = "TRAM CAN QR - CHAY LOCAL"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 17, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(190, 17, 24)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(28, 24)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Vui long cho trong giay lat. He thong se tu mo trinh duyet."
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 88)
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(31, 63)
$form.Controls.Add($subtitle)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "Dang kiem tra moi truong..."
$statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
$statusLabel.AutoSize = $true
$statusLabel.Location = New-Object System.Drawing.Point(31, 104)
$form.Controls.Add($statusLabel)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Location = New-Object System.Drawing.Point(34, 137)
$progress.Size = New-Object System.Drawing.Size(438, 24)
$progress.Minimum = 0
$progress.Maximum = 100
$progress.Value = 8
$progress.Style = "Continuous"
$form.Controls.Add($progress)

$openButton = New-Object System.Windows.Forms.Button
$openButton.Text = "Mo tram can"
$openButton.Size = New-Object System.Drawing.Size(180, 44)
$openButton.Location = New-Object System.Drawing.Point(112, 184)
$openButton.Enabled = $false
$openButton.BackColor = [System.Drawing.Color]::FromArgb(200, 20, 32)
$openButton.ForeColor = [System.Drawing.Color]::White
$openButton.FlatStyle = "Flat"
$openButton.Add_Click({ Start-Process $localUrl })
$form.Controls.Add($openButton)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text = "Dong"
$closeButton.Size = New-Object System.Drawing.Size(100, 44)
$closeButton.Location = New-Object System.Drawing.Point(306, 184)
$closeButton.Add_Click({ $form.Close() })
$form.Controls.Add($closeButton)

function Set-StartupError([string]$message) {
    $script:timer.Stop()
    $statusLabel.Text = $message
    $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(185, 28, 28)
    $progress.Value = 100
    $progress.ForeColor = [System.Drawing.Color]::FromArgb(185, 28, 28)
    $openButton.Enabled = $false
}

function Test-LocalServer {
    try {
        $response = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 1
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$script:attempt = 0
$script:timer = New-Object System.Windows.Forms.Timer
$script:timer.Interval = 700
$script:timer.Add_Tick({
    $script:attempt++
    if (Test-LocalServer) {
        $script:timer.Stop()
        $progress.Value = 100
        $statusLabel.Text = "Da san sang - dang mo trinh duyet"
        $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(15, 130, 70)
        $openButton.Enabled = $true
        Start-Process $localUrl
        return
    }
    $progress.Value = [Math]::Min(92, 20 + ($script:attempt * 5))
    $statusLabel.Text = "Dang khoi dong dich vu local... $($progress.Value)%"
    if ($script:attempt -ge 20) {
        Set-StartupError "Khoi dong qua lau. Hay kiem tra file log cua TramCanQR."
    }
})

$form.Add_Shown({
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Set-StartupError "Chua cai dat moi truong .venv-pilot trong thu muc nay."
        return
    }
    if (-not (Test-Path -LiteralPath $configPath) -and -not (Test-Path -LiteralPath $portableConfigPath)) {
        Set-StartupError "Chua co config.env. Hay chay cai dat lan dau."
        return
    }
    if (Test-LocalServer) {
        $progress.Value = 100
        $statusLabel.Text = "Tram can dang chay - dang mo trinh duyet"
        $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(15, 130, 70)
        $openButton.Enabled = $true
        Start-Process $localUrl
        return
    }
    $progress.Value = 20
    $statusLabel.Text = "Dang nap cau hinh va khoi dong dich vu..."
    try {
        Start-Process -FilePath $pythonPath -ArgumentList "-m", "roll_qr_scale.windows_app" -WorkingDirectory $projectRoot -WindowStyle Hidden
        $script:timer.Start()
    } catch {
        Set-StartupError ("Khong khoi dong duoc: " + $_.Exception.Message)
    }
})

[void]$form.ShowDialog()
