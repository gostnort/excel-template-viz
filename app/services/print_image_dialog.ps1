param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath
)

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Drawing.Printing
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()

$image = [System.Drawing.Image]::FromFile($ImagePath)
try {
    $document = New-Object System.Drawing.Printing.PrintDocument
    $printPage = {
        param($sender, $e)
        $graphics = $e.Graphics
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality

        $dpiX = [float]$image.HorizontalResolution
        $dpiY = [float]$image.VerticalResolution
        if ($dpiX -le 0) { $dpiX = 300.0 }
        if ($dpiY -le 0) { $dpiY = 300.0 }

        $width100 = [int](($image.Width / $dpiX) * 100.0)
        $height100 = [int](($image.Height / $dpiY) * 100.0)
        $maxWidth = $e.MarginBounds.Width
        $maxHeight = $e.MarginBounds.Height
        $scale = [Math]::Min(1.0, [Math]::Min($maxWidth / [double]$width100, $maxHeight / [double]$height100))
        $drawWidth = [int]($width100 * $scale)
        $drawHeight = [int]($height100 * $scale)
        $x = $e.MarginBounds.Left + [int](($maxWidth - $drawWidth) / 2)
        $y = $e.MarginBounds.Top + [int](($maxHeight - $drawHeight) / 2)
        $destRect = New-Object System.Drawing.Rectangle $x, $y, $drawWidth, $drawHeight
        $graphics.DrawImage($image, $destRect)
        $e.HasMorePages = $false
    }
    $document.add_PrintPage($printPage)

    $preview = New-Object System.Windows.Forms.PrintPreviewDialog
    $preview.Document = $document
    $preview.Text = "打印预览"
    $preview.Width = 960
    $preview.Height = 720
    $preview.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $preview.ShowDialog() | Out-Null
    exit 0
}
finally {
    $image.Dispose()
}
