scMM WIN-01 offline validation kit (Windows 11 x64)

This is a developer validation kit, not the scMM application installer.
It does not start the website, initialize accounts, read experimental data,
change system Python/PATH, or install a Windows service.

1. Copy the ZIP to your Windows 11 x64 PC. Compare its SHA-256 with SHA256SUMS
   provided separately. In PowerShell:
       Get-FileHash .\scMM-WIN01-win-x64.zip -Algorithm SHA256
2. After checking the source and checksum, remove this downloaded ZIP's mark
   of the web if needed, then extract it using File Explorer:
       Unblock-File -LiteralPath .\scMM-WIN01-win-x64.zip
   This trusts this specific kit only; it does not change system policy.
3. Disconnect network access. Open 64-bit Windows PowerShell in the extracted
   directory. Run with a new local NTFS work folder, for example:
       powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\run-win01.ps1 -WorkRoot D:\scMM-WIN01-run1
   RemoteSigned applies to this process only. Organization policy may still
   reject scripts; follow your administrator's policy instead of bypassing it.
   You do not need administrator privileges, Python, uv, Node, or .NET.
4. Wait for file verification, offline assembly, original-path computation,
   and computation after relocation into a Chinese/space path.
   Diagnostics are preserved on success and failure. Do not delete the folder
   or retry with the same WorkRoot; choose another new path for each run.
5. Return these small files for review (never the generated matrices):
       session.json, before.json, after.json, diagnostics.txt
   On early failure, return whichever files were produced and the error text.
   Diagnostics can contain local folder names; inspect them before sharing.
6. State your Windows version, whether you disconnected networking, and
   whether this PC already had Python/Node/.NET/developer tools installed.
   A pass on an existing development PC does not prove clean-machine support.
   Another Chinese Windows user account requires a separate run under that
   account; a Chinese directory alone does not establish that condition.

Dependencies remain in their original hashed wheels with their notices.
The bundled uv is dual MIT/Apache-2.0; notices are in licenses/.
Python's notices are inside the verified Python archive/runtime.
This kit does not include the Thermo reader or vendor DLLs. RAW, application
startup, ACL/tasks and the complete installer remain separate milestones.
