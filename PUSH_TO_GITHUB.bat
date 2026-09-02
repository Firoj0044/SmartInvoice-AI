@echo off
title SmartInvoice AI - GitHub Push Helper
echo ==========================================
echo   SmartInvoice AI - One-Click GitHub Push
echo ==========================================
echo.
echo This will push your code to GitHub.
echo You'll be asked for your GitHub credentials (token).
echo.
set /p GHUSER="Enter your GitHub username: "
echo.
echo Get a token at: https://github.com/settings/tokens
echo (Click 'Generate new token (classic)' - check 'repo' scope)
echo.
set /p GHTOKEN="Paste your Personal Access Token (hidden): "

cd /d "%~dp0"

REM Initialize git if needed
if not exist ".git" (
    echo.
    echo Initializing git repository...
    git init
    git branch -M main
)

REM Configure git user
git config user.name "%GHUSER%"
git config user.email "%GHUSER%@users.noreply.github.com"

REM Add remote
git remote remove origin 2>nul
git remote add origin https://%GHUSER%:%GHTOKEN%@github.com/%GHUSER%/SmartInvoice-AI.git

REM Pull existing content (in case README was added)
git pull origin main --allow-unrelated-histories --no-edit 2>nul

REM Stage and commit
git add .
git commit -m "Add SmartInvoice AI v1.0 - landing + backend + frontend"

REM Push
echo.
echo Pushing to GitHub...
git push -u origin main

if errorlevel 0 (
    echo.
    echo ==========================================
    echo   SUCCESS! Pushed to GitHub.
    echo ==========================================
    echo.
    echo Next step: Deploy to Render.com
    echo   1. Go to https://render.com
    echo   2. Click 'New +' - 'Blueprint'
    echo   3. Connect your GitHub repo
    echo   4. Add OPENROUTER_API_KEY env var
    echo   5. Click Apply
    echo.
) else (
    echo.
    echo ==========================================
    echo   PUSH FAILED
    echo ==========================================
    echo Check your username and token, then try again.
)

pause