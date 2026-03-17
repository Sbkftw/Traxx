[CmdletBinding()]
param(
    [ValidateSet("classic", "cli-tool")]
    [string]$Variant = "cli-tool"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$assetsDir = Join-Path $projectRoot "assets"
$baseName = if ($Variant -eq "classic") { "traxx-icon" } else { "traxx-cli-icon" }
$pngPath = Join-Path $assetsDir "$baseName.png"
$icoPath = Join-Path $assetsDir "$baseName.ico"
$canonicalPngPath = Join-Path $assetsDir "traxx-icon.png"
$canonicalIcoPath = Join-Path $assetsDir "traxx.ico"

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

function Draw-ClassicIcon {
    param(
        [System.Drawing.Graphics]$Graphics
    )

    $backgroundRect = New-Object System.Drawing.Rectangle 16, 16, 224, 224
    $backgroundBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        $backgroundRect,
        [System.Drawing.Color]::FromArgb(255, 8, 29, 43),
        [System.Drawing.Color]::FromArgb(255, 18, 59, 82),
        45
    )

    $accentBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.Rectangle 68, 44, 136, 136),
        [System.Drawing.Color]::FromArgb(255, 0, 230, 168),
        [System.Drawing.Color]::FromArgb(255, 39, 199, 255),
        35
    )

    $backgroundPath = New-RoundedRectPath -X 16 -Y 16 -Width 224 -Height 224 -Radius 56
    $Graphics.FillPath($backgroundBrush, $backgroundPath)

    $glowBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(28, 60, 234, 255))
    $Graphics.FillEllipse($glowBrush, 45, 32, 142, 142)

    $recordFill = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 10, 32, 48))
    $Graphics.FillEllipse($recordFill, 64, 52, 124, 124)

    $ringPen = New-Object System.Drawing.Pen($accentBrush, 5)
    $ringPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $Graphics.DrawEllipse($ringPen, 64, 52, 124, 124)

    $innerRingPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(96, 88, 215, 255), 3)
    $Graphics.DrawEllipse($innerRingPen, 77, 65, 98, 98)
    $Graphics.DrawEllipse($innerRingPen, 93, 81, 66, 66)

    $hubBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 20, 59, 81))
    $hubPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 201, 251, 255), 3)
    $Graphics.FillEllipse($hubBrush, 118, 106, 18, 18)
    $Graphics.DrawEllipse($hubPen, 118, 106, 18, 18)

    $armGlowPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(80, 119, 243, 255), 8)
    $armGlowPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $armGlowPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $Graphics.DrawLine($armGlowPen, 152, 85, 198, 101)

    $armPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 216, 252, 255), 5)
    $armPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $armPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $Graphics.DrawLine($armPen, 152, 85, 198, 101)

    $headPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 158, 242, 255), 12)
    $headPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $headPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $Graphics.DrawLine($headPen, 198, 101, 225, 101)

    $pivotOuter = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 201, 251, 255))
    $pivotInner = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 10, 34, 51))
    $Graphics.FillEllipse($pivotOuter, 191, 94, 14, 14)
    $Graphics.FillEllipse($pivotInner, 195, 98, 6, 6)

    $textBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 241, 254, 255))
    $font = New-Object System.Drawing.Font("Segoe UI", 34, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $Graphics.DrawString("TR", $font, $textBrush, 128, 196, $format)

    $font.Dispose()
    $format.Dispose()
    $textBrush.Dispose()
    $pivotInner.Dispose()
    $pivotOuter.Dispose()
    $headPen.Dispose()
    $armPen.Dispose()
    $armGlowPen.Dispose()
    $hubPen.Dispose()
    $hubBrush.Dispose()
    $innerRingPen.Dispose()
    $ringPen.Dispose()
    $recordFill.Dispose()
    $glowBrush.Dispose()
    $backgroundPath.Dispose()
    $backgroundBrush.Dispose()
    $accentBrush.Dispose()
}

function Draw-CliToolIcon {
    param(
        [System.Drawing.Graphics]$Graphics
    )

    $backgroundRect = New-Object System.Drawing.Rectangle 16, 16, 224, 224
    $backgroundBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        $backgroundRect,
        [System.Drawing.Color]::FromArgb(255, 9, 18, 28),
        [System.Drawing.Color]::FromArgb(255, 20, 37, 56),
        90
    )
    $backgroundPath = New-RoundedRectPath -X 16 -Y 16 -Width 224 -Height 224 -Radius 40
    $Graphics.FillPath($backgroundBrush, $backgroundPath)

    $framePath = New-RoundedRectPath -X 34 -Y 44 -Width 188 -Height 142 -Radius 22
    $frameBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 7, 15, 24))
    $framePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 67, 97, 126), 3)
    $Graphics.FillPath($frameBrush, $framePath)
    $Graphics.DrawPath($framePen, $framePath)

    $topBarBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 18, 30, 44))
    $Graphics.FillRectangle($topBarBrush, 36, 46, 184, 24)

    $redDot = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 255, 102, 102))
    $amberDot = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 255, 196, 64))
    $greenDot = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 61, 220, 151))
    $Graphics.FillEllipse($redDot, 48, 53, 8, 8)
    $Graphics.FillEllipse($amberDot, 62, 53, 8, 8)
    $Graphics.FillEllipse($greenDot, 76, 53, 8, 8)

    $caretPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 82, 235, 179), 6)
    $caretPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $caretPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $Graphics.DrawLine($caretPen, 64, 101, 83, 118)
    $Graphics.DrawLine($caretPen, 83, 118, 64, 135)

    $cursorPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 39, 199, 255), 6)
    $cursorPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Square
    $cursorPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Square
    $Graphics.DrawLine($cursorPen, 97, 136, 121, 136)

    $wavePen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 39, 199, 255), 4)
    $wavePen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $wavePen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $Graphics.DrawBezier($wavePen, 126, 121, 139, 107, 152, 135, 166, 121)
    $Graphics.DrawBezier($wavePen, 170, 121, 182, 108, 195, 134, 207, 120)

    $textBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 233, 250, 255))
    $titleFont = New-Object System.Drawing.Font("Consolas", 29, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $subtitleFont = New-Object System.Drawing.Font("Consolas", 14, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $Graphics.DrawString(">_", $titleFont, $textBrush, 128, 194, $format)
    $Graphics.DrawString("TRAXX", $subtitleFont, $textBrush, 128, 223, $format)

    $subtitleFont.Dispose()
    $titleFont.Dispose()
    $format.Dispose()
    $textBrush.Dispose()
    $wavePen.Dispose()
    $cursorPen.Dispose()
    $caretPen.Dispose()
    $greenDot.Dispose()
    $amberDot.Dispose()
    $redDot.Dispose()
    $topBarBrush.Dispose()
    $framePen.Dispose()
    $frameBrush.Dispose()
    $framePath.Dispose()
    $backgroundBrush.Dispose()
    $backgroundPath.Dispose()
}

$size = 256
$bitmap = New-Object System.Drawing.Bitmap $size, $size
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$graphics.Clear([System.Drawing.Color]::Transparent)

if ($Variant -eq "classic") {
    Draw-ClassicIcon -Graphics $graphics
} else {
    Draw-CliToolIcon -Graphics $graphics
}

$bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-PngAsIco -SourcePngPath $pngPath -DestinationIcoPath $icoPath

[System.IO.File]::Copy($pngPath, $canonicalPngPath, $true)
[System.IO.File]::Copy($icoPath, $canonicalIcoPath, $true)

$graphics.Dispose()
$bitmap.Dispose()

Write-Host "Generated assets:"
Write-Host " - $pngPath"
Write-Host " - $icoPath"
Write-Host "Selected build icon:"
Write-Host " - $canonicalPngPath"
Write-Host " - $canonicalIcoPath"
