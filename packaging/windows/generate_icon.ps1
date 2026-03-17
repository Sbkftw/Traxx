$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$assetsDir = Join-Path $projectRoot "packaging\assets"
$pngPath = Join-Path $assetsDir "traxx-icon.png"
$icoPath = Join-Path $assetsDir "traxx.ico"

New-Item -ItemType Directory -Force -Path $assetsDir | Out-Null

Add-Type -AssemblyName System.Drawing

function New-RoundedRectPath {
    param(
        [int]$X,
        [int]$Y,
        [int]$Width,
        [int]$Height,
        [int]$Radius
    )

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $diameter = $Radius * 2
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc($X + $Width - $diameter, $Y + $Height - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function Write-PngAsIco {
    param(
        [string]$SourcePngPath,
        [string]$DestinationIcoPath
    )

    $pngBytes = [System.IO.File]::ReadAllBytes($SourcePngPath)
    $stream = [System.IO.File]::Open($DestinationIcoPath, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter($stream)
    $writer.Write([UInt16]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]1)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]32)
    $writer.Write([UInt32]$pngBytes.Length)
    $writer.Write([UInt32]22)
    $writer.Write($pngBytes)
    $writer.Flush()
    $writer.Dispose()
    $stream.Dispose()
}

$size = 256
$bitmap = New-Object System.Drawing.Bitmap $size, $size
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$graphics.Clear([System.Drawing.Color]::Transparent)

$backgroundPath = New-RoundedRectPath -X 20 -Y 20 -Width 216 -Height 216 -Radius 44
$backgroundBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
    (New-Object System.Drawing.Rectangle 20, 20, 216, 216),
    [System.Drawing.Color]::FromArgb(255, 11, 17, 26),
    [System.Drawing.Color]::FromArgb(255, 23, 34, 48),
    90
)
$borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 49, 214, 184), 4)

$graphics.FillPath($backgroundBrush, $backgroundPath)
$graphics.DrawPath($borderPen, $backgroundPath)

$windowPath = New-RoundedRectPath -X 44 -Y 56 -Width 168 -Height 112 -Radius 18
$windowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 8, 13, 20))
$windowPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 56, 82, 106), 2)
$graphics.FillPath($windowBrush, $windowPath)
$graphics.DrawPath($windowPen, $windowPath)

$barBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 17, 27, 39))
$graphics.FillRectangle($barBrush, 46, 58, 164, 18)

$dot1 = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 255, 95, 86))
$dot2 = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 255, 189, 46))
$dot3 = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 39, 201, 63))
$graphics.FillEllipse($dot1, 56, 63, 6, 6)
$graphics.FillEllipse($dot2, 67, 63, 6, 6)
$graphics.FillEllipse($dot3, 78, 63, 6, 6)

$promptPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 49, 214, 184), 7)
$promptPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
$promptPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$graphics.DrawLine($promptPen, 74, 105, 94, 122)
$graphics.DrawLine($promptPen, 94, 122, 74, 139)

$cursorPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 235, 247, 255), 7)
$cursorPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Square
$cursorPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Square
$graphics.DrawLine($cursorPen, 108, 138, 134, 138)

$titleBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 235, 247, 255))
$titleFont = New-Object System.Drawing.Font("Consolas", 26, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$format = New-Object System.Drawing.StringFormat
$format.Alignment = [System.Drawing.StringAlignment]::Center
$graphics.DrawString("TX", $titleFont, $titleBrush, 128, 184, $format)

$bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-PngAsIco -SourcePngPath $pngPath -DestinationIcoPath $icoPath

$format.Dispose()
$titleFont.Dispose()
$titleBrush.Dispose()
$cursorPen.Dispose()
$promptPen.Dispose()
$dot3.Dispose()
$dot2.Dispose()
$dot1.Dispose()
$barBrush.Dispose()
$windowPen.Dispose()
$windowBrush.Dispose()
$windowPath.Dispose()
$borderPen.Dispose()
$backgroundBrush.Dispose()
$backgroundPath.Dispose()
$graphics.Dispose()
$bitmap.Dispose()

Write-Host "Generated assets:"
Write-Host " - $pngPath"
Write-Host " - $icoPath"
