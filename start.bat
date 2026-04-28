@echo off
title ЕмоАтлас Репостер
cd /d "C:\Users\ekono\OneDrive\Робочий стіл\reposter"
echo Запуск ЕмоАтлас Репостер...
echo.
echo Відкрийте браузер: http://localhost:5000
echo Для зупинки натисніть Ctrl+C
echo.
start "" "http://localhost:5000"
python -m web.app
pause
