@echo off
cd /d "C:\Users\Administrator\Desktop\bs-push"
echo === GIT ADD === > C:\Users\Administrator\Desktop\gp4.log
git add -A >> C:\Users\Administrator\Desktop\gp4.log 2>&1
echo === GIT COMMIT === >> C:\Users\Administrator\Desktop\gp4.log
git commit -m "feat: v2.1 multi-functional zones + kiosk_v2 + remove React frontend" >> C:\Users\Administrator\Desktop\gp4.log 2>&1
echo === GIT PUSH === >> C:\Users\Administrator\Desktop\gp4.log
git push origin main >> C:\Users\Administrator\Desktop\gp4.log 2>&1
echo === DONE === >> C:\Users\Administrator\Desktop\gp4.log
