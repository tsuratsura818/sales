@echo off
cd /d "%~dp0"
title SellBuddy Claude Bridge
echo ============================================
echo   SellBuddy 秘書チャット ローカルブリッジ
echo ============================================
echo.
echo  この画面を開いている間だけ秘書チャットが使えます。
echo  終了するには Ctrl+C か、この画面を閉じてください。
echo.
python claude_bridge.py
pause
