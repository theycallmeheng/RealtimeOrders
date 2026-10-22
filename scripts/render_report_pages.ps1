param([string]$Source='report/Nhom17_RealtimeOrders_Report.docx',[string]$OutputDirectory='runtime/report-pages-qa')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$sourcePath=(Resolve-Path -LiteralPath $Source).Path
$outputPath=[IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputDirectory))
[IO.Directory]::CreateDirectory($outputPath)|Out-Null
$word=$null;$document=$null;$owned=$false
$before=@(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
try{
    $word=New-Object -ComObject Word.Application
    if($word.Documents.Count -ne 0){throw 'Unexpected user documents; rendering cancelled'}
    $owned=$true;$word.Visible=$false;$word.DisplayAlerts=0;$word.AutomationSecurity=3
    $new=@(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Where-Object {$_.Id -notin $before})
    if($new.Count -eq 1){$new[0].Id | Set-Content -LiteralPath (Join-Path $outputPath 'word.pid')}
    $document=$word.Documents.Open($sourcePath,$false,$true,$false)
    $document.ActiveWindow.View.Type=3
    $document.Repaginate();$count=$document.ComputeStatistics(2)
    $pages=$document.ActiveWindow.ActivePane.Pages
    if($pages.Count -ne $count){throw 'Native page count mismatch'}
    Write-Host "Native page rendering: $count pages"
    for($index=1;$index -le $count;$index++){
        $page=$pages.Item($index)
        [byte[]]$bits=$page.EnhMetaFileBits
        $stream=[IO.MemoryStream]::new($bits)
        $image=[Drawing.Imaging.Metafile]::new($stream)
        $width=[int][Math]::Ceiling($page.Width/72*150);$height=[int][Math]::Ceiling($page.Height/72*150)
        $bitmap=[Drawing.Bitmap]::new($width,$height);$bitmap.SetResolution(150,150)
        $graphics=[Drawing.Graphics]::FromImage($bitmap)
        try{
            $graphics.Clear([Drawing.Color]::White)
            $graphics.TextRenderingHint=[Drawing.Text.TextRenderingHint]::AntiAliasGridFit
            $graphics.SmoothingMode=[Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $graphics.InterpolationMode=[Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.DrawImage($image,[Drawing.Rectangle]::new(0,0,$width,$height))
            $bitmap.Save((Join-Path $outputPath ('page-{0:D2}.png' -f $index)),[Drawing.Imaging.ImageFormat]::Png)
        }finally{$graphics.Dispose();$bitmap.Dispose();$image.Dispose();$stream.Dispose()}
        Write-Host "Rendered page $index"
    }
}finally{
    $discard=0
    if($document){$document.Close([ref]$discard);[Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)|Out-Null}
    if($owned -and $word){$word.Quit([ref]$discard)}
    if($word){[Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)|Out-Null}
}
