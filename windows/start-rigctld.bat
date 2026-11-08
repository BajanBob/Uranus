@echo off
rem Edit these three lines for your rig. Find your model number with:  rigctl -l
rem Examples: IC-9700 = 3081, IC-705 = 3085, FT-991 = 1035  (check with rigctl -l)
set RIG_MODEL=3081
set COM_PORT=COM3
set BAUD=19200
rem Hamlib for Windows: https://github.com/Hamlib/Hamlib/releases  (add its bin folder to PATH)
rigctld -m %RIG_MODEL% -r %COM_PORT% -s %BAUD% -t 4532
pause
