Set oWS = WScript.CreateObject("WScript.Shell")
sDesktop = oWS.SpecialFolders("Desktop")
sLinkFile = sDesktop & "\EmoAtlas.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "C:\Users\ekono\OneDrive\Робочий стіл\reposter\start.bat"
oLink.WorkingDirectory = "C:\Users\ekono\OneDrive\Робочий стіл\reposter"
oLink.Description = "EmoAtlas Reposter"
oLink.IconLocation = "C:\Windows\System32\SHELL32.dll,25"
oLink.Save
WScript.Echo "Shortcut created!"
