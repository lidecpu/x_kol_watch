Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
cmd = """" & pythonw & """ """ & scriptDir & "\x_kol_daily.py"" --send --telegram-mode focus"
shell.CurrentDirectory = scriptDir
shell.Run cmd, 0, False
