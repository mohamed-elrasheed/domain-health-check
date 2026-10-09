' Runs one of the repository's console commands with no visible window, waits for it to finish, and hands
' its exit code back to whoever started this script, so Task Scheduler records the real result.
'
'   wscript.exe scripts\run-hidden.vbs <exe> [args...] <log name>
'
' <exe> is a program in .venv\Scripts, run from the repository root. Its stdout and stderr are appended to
' logs\<log name>-task.log. For example:
'
'   wscript.exe scripts\run-hidden.vbs domain-health-check.exe intake intake
'
' runs .venv\Scripts\domain-health-check.exe intake >> logs\intake-task.log 2>&1
'
' Exit codes: the command's own, or 64 when this script was called with too few arguments.
Option Explicit

Dim shell, fso, repo, exe, logName, args, i, cmd

If WScript.Arguments.Count < 2 Then
    WScript.Quit 64
End If

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' This script lives in <repo>\scripts, so the repository is its folder's parent.
repo = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
If Not fso.FolderExists(repo & "\logs") Then
    fso.CreateFolder repo & "\logs"
End If

exe = WScript.Arguments(0)
logName = WScript.Arguments(WScript.Arguments.Count - 1)
args = ""
For i = 1 To WScript.Arguments.Count - 2
    args = args & " " & Quoted(WScript.Arguments(i))
Next

cmd = "cmd /c cd /d """ & repo & """ && .venv\Scripts\" & exe & args & " >> logs\" & logName & "-task.log 2>&1"

' 0: no window. True: wait, and return the command's exit code.
WScript.Quit shell.Run(cmd, 0, True)

' An argument with a space in it is quoted again, since WScript hands it over without its quotes.
Function Quoted(arg)
    If InStr(arg, " ") > 0 Then
        Quoted = """" & arg & """"
    Else
        Quoted = arg
    End If
End Function
