@echo off
rem 指数君盯盘 —— 双击本文件即可启动（无黑框）
setlocal
set "PYW=C:\Users\18633\AppData\Local\Programs\Python\Python311\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0ticker.pyw"
exit
