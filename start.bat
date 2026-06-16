@echo off
cd /d "%~dp0"
echo 正在安装依赖...
python -m pip install -r requirements.txt
echo.
echo 正在启动 MoodTune AI...
echo 浏览器地址: http://localhost:8501
echo.
python -m streamlit run app.py
pause
