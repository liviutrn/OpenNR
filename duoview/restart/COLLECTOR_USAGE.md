# DuoView restart evidence collector

Run `Collect-DuoViewRestartEvidence.ps1` in Windows PowerShell 5.1 separately
from STALKER 2 and UEVR. It writes a timestamp/PID-named ZIP to the current
directory unless `-OutputDirectory` is supplied. The ZIP contains a readable
`summary.txt` and `collection-manifest.json`; the manifest records included,
missing, excluded, and truncated candidates with hashes for captured files.

Example, launched before the game with its process ID:

```powershell
.\Collect-DuoViewRestartEvidence.ps1 `
  -GameSavedRoot 'D:\Games\STALKER2\Saved' `
  -UevrRoot "$env:LOCALAPPDATA\UEVR" `
  -PackageRoot 'D:\DuoViewRestart' `
  -WatchPid 12345 `
  -OutputDirectory "$env:USERPROFILE\Desktop"
```

For a collection after the game has already exited, omit `-WatchPid`. An
explicit log or settings file can be supplied with `-UevrLogPath`,
`-SettingsPath`, or `-DiagnosticPath`. `-IncludeDumps` opts in to copying only
recent dumps found directly in `Saved\Crashes` or one child directory. Dumps
can contain sensitive memory. The script caps each dump at 20 MiB, all dumps
at 32 MiB, and all staged evidence at 100 MiB. Oversized dumps are excluded;
they are not partially copied.

Discovery is intentionally shallow. The default UEVR candidate is
`%LOCALAPPDATA%\UEVR`, but no verified UEVR runtime log location is established;
missing paths appear in the manifest. There is no automatic STALKER 2 path
search: pass the game's `Saved` directory using `-GameSavedRoot`. UEVR log
discovery checks only top-level `.log`/`.txt` files and an immediate `logs`
directory. Settings discovery checks only `settings.ini`, `settings.json`,
`config.ini`, and `config.json` at the UEVR root. Game collection is limited to
recent files in `Saved\Logs`, `Saved\Crashes` (including one child directory),
and the `Saved\Config\Windows`, `WindowsNoEditor`, and `Win64` directories.
Package metadata is an exact filename allowlist in `PackageRoot`.

`-WatchPid` polls at 900 ms intervals for at most `-WatchTimeoutSeconds`
(default one hour, maximum six hours). It never terminates the game. A timeout
means collection proceeds while the process may still be running.

The collector reads no process environment dump, does not scan a user profile
recursively, and does not upload data. Pattern-based redaction is applied to
text, but it cannot guarantee that every sensitive value is removed. Review
the ZIP before sharing it. Summary matches for `[DuoViewRestart]` report only
producer copy-boundary log fields; they do not determine whether a control
passed. Engine source-generation linkage, `xrEndFrame` acceptance, headset
presentation, and PSVR2 connection/tracking remain unavailable from these
artifacts.
