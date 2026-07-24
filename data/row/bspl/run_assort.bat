@echo off
chcp 65001
call "%AIREAD_HOME%\scripts\set_envs.bat"
set MAIN_CLASS_NAME=co.jp.ariseinnovation.AIReadEE.AIReadEE

if exist debug ( rd /s /q debug )
if exist failed ( rd /s /q failed )
if exist logs ( rd /s /q logs )
if exist output ( rd /s /q output )
if exist success ( rd /s /q success )

xcopy /e /i /y input input_work

"%AIREAD_JAVA%/java" -Xmx8192m -Dhttps.protocols=TLSv1.2 -classpath "%CLASSPATH%" %MAIN_CLASS_NAME% -s ".\AIRead_setting.ini" -A "AIRead_conf\ClassifyDir"

rd /s /q input_work

pause;
