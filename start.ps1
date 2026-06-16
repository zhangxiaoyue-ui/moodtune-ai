# MoodTune AI 一键启动脚本
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "正在安装依赖..." -ForegroundColor Cyan
python -m pip install -r requirements.txt

Write-Host "`n正在启动 MoodTune AI..." -ForegroundColor Green
Write-Host "启动后请在浏览器打开: http://localhost:8501`n" -ForegroundColor Yellow
python -m streamlit run app.py
