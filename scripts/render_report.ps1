param([string]$Source='report/Nhom17_RealtimeOrders_Report.docx',[string]$OutputDirectory='runtime/report-pages-qa')
# Native Word page rendering avoids the fixed-format PDF/XPS converter, which
# stalls on this machine. No user document or application instance is reused.
& (Join-Path $PSScriptRoot 'render_report_pages.ps1') -Source $Source -OutputDirectory $OutputDirectory
