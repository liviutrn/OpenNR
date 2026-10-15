# DuoView restart evidence collector

Run `Collect-DuoViewRestartEvidence.ps1` in Windows PowerShell 5.1 separately
from STALKER 2 and UEVR. It writes a timestamp/PID-named ZIP to the current
directory unless `-OutputDirectory` is supplied. The ZIP contains a readable
`summary.txt` and `collection-manifest.json`; the manifest records included,
missing, excluded, and truncated candidates with hashes for captured files.

Example, launched while the game is running so it can collect after exit:

```powershell
.\Collect-DuoViewRestartEvidence.ps1 `
  -WatchPid 12345 `
  -OutputDirectory "$env:USERPROFILE\Desktop"
```

For a collection after the game has already exited, omit `-WatchPid`. An
explicit log or settings file can be supplied with `-UevrLogPath`,
`-SettingsPath`, or `-DiagnosticPath`. Pass `-GameExecutableStem` if the game
uses a different executable filename. `-IncludeDumps` opts in to copying only
recent dumps found directly in `Saved\Crashes` or one child directory. Dumps
can contain sensitive memory. The script caps each dump at 20 MiB, all dumps
at 32 MiB, and all staged evidence at 100 MiB. Oversized dumps are excluded;
they are not partially copied.

The pinned UEVR backend creates its persistent logger at
`%APPDATA%\UnrealVRMod\<executable-stem>\log.txt` (`Framework.cpp` in backend
pin `5ac7edc207866569334175e4ed8a7517971547f6`). The default stem is
`Stalker2-Win64-Shipping`; when `-WatchPid` is supplied, the collector first
tries to derive the live process executable stem before waiting. Use
`-GameExecutableStem` for a different or post-crash executable name. The ZIP
manifest records whether the profile directory existed and how its stem was
selected. An explicit `-UevrRoot` uses a shallow candidate scan of its direct
`.log`/`.txt` files and immediate `logs` child; the source-derived default reads
only `log.txt`.

The default STALKER 2 Steam Saved candidate is
`%LOCALAPPDATA%\Stalker2\Saved`, and collection is conditional on that exact
directory existing. The official [save-management article](https://www.stalker2.com/news/saves-managing-manual/)
documents its `STEAM` child; the official [mods FAQ](https://www.stalker2.com/news/mods-cost-of-hope-update-2-0-faq)
documents its `Config` child. The collector never enumerates or copies save
content under `Saved\STEAM`. It inspects only recent files in `Saved\Logs`,
`Saved\Crashes` (including one child directory), and the `Saved\Config\Windows`,
`WindowsNoEditor`, and `Win64` directories. These are bounded candidate
locations; their existence does not identify the installed game version. Pass
`-GameSavedRoot` for another store or custom location.

The pinned UEVR `Framework.cpp` writes `config.txt` under that same per-executable
persistent profile (lines 1188-1196). Settings discovery checks this
source-verified `config.txt` plus the exact
candidate names `settings.ini`, `settings.json`, `config.ini`, and `config.json`
at the resolved UEVR profile root. `-SettingsPath` accepts local files with
allowlisted text extensions; `.txt` is permitted only when the leaf name is
exactly `config.txt`. Package metadata is an exact filename allowlist in
`PackageRoot`: the baseline lock/source reports, backend patch and source
snapshot manifests, `STATUS.md`, `EXPERIMENTS.md`, `READ_FIRST.txt`, and the
shipped collector script and usage guide. The workflow places
`package-sha256.json` beside those files; it lists SHA-256 values for every
package file present before the hash manifest was created and excludes itself
to avoid a recursive definition. The collector discovers this exact filename
automatically. You can also pass `-PackageHashManifestPath
<path-to-package-sha256.json>` for an external copy. The collector does not
enumerate other package files.

`-WatchPid` polls at 900 ms intervals for at most `-WatchTimeoutSeconds`
(default one hour, maximum six hours). It never terminates the game. A timeout
means collection proceeds while the process may still be running. When no
`-GameExecutableStem` is supplied, the collector tries to capture the watched
process's executable stem before waiting; otherwise it uses the scoped default
`Stalker2-Win64-Shipping`.

The watcher checks whether that PID still exists; it does not retain or
revalidate a process creation identity, so PID reuse is not ruled out. Default
UEVR and STALKER paths are candidate conventions: an existing directory records
that the candidate exists, not that the running game wrote those files or which
game/runtime version is installed. Logger matches are bounded tail matches;
they do not measure exact per-frame events or imply that every frame was
observed.

The collector reads no process environment dump, does not scan a user profile
recursively, and does not upload data. Pattern-based redaction is applied to
text, but it cannot guarantee that every sensitive value is removed. Review
the ZIP before sharing it. Summary matches for `[DuoViewRestart]` report only
producer copy-boundary log fields; they do not determine whether a control
passed. Engine source-generation linkage, `xrEndFrame` acceptance, headset
presentation, and PSVR2 connection/tracking remain unavailable from these
artifacts.

On Windows, run `tests\collector_smoke_tests.ps1` in Windows PowerShell 5.1 to
parse the collector and exercise the bounded fixture, manifest, redaction,
truncation, missing-file, and no-save-content checks.
