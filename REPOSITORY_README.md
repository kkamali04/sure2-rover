# sure² — rover planner and local controller

Edit rover stations and probe heights in 2D, preview the same plan in 3D, and use a separate local manual controller for a WAVE ROVER. The default is **2 rows × 6 stations × 3 heights = 36 planned points**. XY and heights are millimeters. The preview uses the supplied cabinet/rover concept design.

## Try it without a rover

Open **SURE2_Planner.html** in Chrome or Edge, or use the repository's GitHub Pages link. No installation or account is required for browser planning.

1. In **Edit 2D**, click a footprint. Arrow keys nudge 5 mm; Shift nudges 1 mm. Drag it or right-click **Change / Direction / Delete** for exact values.
2. Choose **Z heights** and drag a dot up/down in millimeters, or click it to type an exact value. Dragging stays within the entered geometry and keeps the three heights ordered. If dots overlap, click the corresponding Z input to bring that dot to the front. Heights apply to all stations. Use **+ Station** for custom points, or **Settings → Rows / Stations across X → Generate alternating rows**. Supports 1–200 stations, subject to geometry validation.
3. **Preview 3D** shows the updated positions and heights. The viewer and editor use the same plan, not separate files. Choose Perspective, Top, Front or Side; drag to orbit, scroll to zoom. **Visible components** controls the original scene layers.
4. Choose 30× or 60× and **Play** for a quick demonstration. The timeline and **Next station** inspect the route without waiting through every dwell. These animate only the screen.
5. **Settings → Download JSON** saves the complete plan. Send that file to a teammate; they can import it through Settings. Changes are local to the browser and are lost on refresh unless exported. There is no shared database or live collaborative editing.

Professors can edit points and heights on the public site and see the changes in 3D immediately. They cannot operate your rover through GitHub Pages. The site's Debug tab displays the remote UI disabled and links to the local controller.

## Windows: one launcher

Download the repository ZIP, **Extract All**, then double-click **SURE2.bat**. Keep all extracted files together; do not run inside the ZIP.

| Menu | What it does |
|---|---|
| 1 — Preview | Opens the self-contained HTML; no Python needed |
| 2 — Simulator | Finds Python 3.10+, creates `.venv`, starts localhost simulation and opens the app |
| 3 — Live | Requires typing `LIVE` and entering the rover IP; starts the manual controller disarmed |
| 4 — USB dependency | Installs optional pyserial into `.venv`; internet needed the first time |
| 5 — Check/setup | Checks Python and imports; no controller or rover connection |
| 6 — Software tests | Runs Python tests with fake/simulated transports; no rover |

The simulator and HTTP Wi-Fi controller use Python's standard library. Node/Playwright are only for developer browser tests. If Python is missing, the launcher offers a per-user Python installation through Windows Package Manager; otherwise install Python 3.10+ from [python.org](https://www.python.org/downloads/windows/) and rerun. It does not change machine-wide PowerShell policy, firmware or networking. The BAT applies execution policy only to its own local helper process; managed computers may require IT approval.

Command shortcuts: `SURE2.bat Preview`, `SURE2.bat Simulate`, `SURE2.bat Check`, `SURE2.bat Test`. Advanced checks: `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_and_run.ps1 -Mode Check -NoBrowser -NoPythonInstall`.

An already-running controller of the requested mode is reused. An occupied/mismatched port is reported; no unrelated process is killed. Stop, close, and reopen the controller after updating its code. Close its PowerShell window with Ctrl+C when finished.

## Connect the real rover later

1. Raise its wheels, keep its power switch accessible, connect the computer to rover Wi-Fi and close other control clients. Internet is unnecessary after installation. Ethernet plus Wi-Fi is environment-dependent and has not been verified on the owner's computer.
2. Run SURE2.bat, select Live, type `LIVE` when physically ready, and enter the rover's actual IP (default 192.168.4.1).
3. Open the local Debug controller at `http://127.0.0.1:8766/debug`. It starts disarmed. The operator arms and holds direction controls; releasing commands neutral. STOP/Space/Escape disarm. Reconnect requires explicit rearming.
4. Use the controller's stopped-state telemetry and test-record tools. Raw commands, responses and observations are logged under `test_runs`; connection faults also appear in `controller_log.jsonl`. Retention: latest 10 managed sessions, 90 MB budget; runtime data is excluded from Git.

No sequence of planner points is executed automatically. Accurate physical XY, lift control/feedback and airflow sensor acquisition are not implemented. Catalog dimensions and the lift model are provisional. Physical turning, calibration, stopping distance and a 5 mm tolerance still require hardware testing.

## Timing

Defaults: **2.5 s settle + 5 s dwell per point**. Click **Timing** to edit them. Settling updates immediately; **Apply dwell to all stations** updates every station. Right-click a station to set its own dwell. Imported plans retain their saved values; imports are not silently halved.

| Part of the default 36-point preview | Time |
|---|---:|
| Settle + dwell: 36 × 7.5 s | 270 s (4:30) |
| Lift between heights: 24 × 20 s | 480 s |
| Park lift: 12 × 20 s | 240 s |
| Travel: 11 × 3 s | 33 s |
| Two 90° turns: 2 × 3 s | 6 s |
| **Total at 1×** | **1029 s (17:09)** |

At 60×, playback takes about 17 seconds without changing the plan. Halving point waits does not halve lift/travel time. Motion durations are editable visual assumptions, not measured actuator speeds; dwell is elapsed time, not evidence of acquired samples.

## Publish this full repository on GitHub Pages

With Git and GitHub CLI installed, run **PUBLISH_GITHUB.bat** from this package in your own Windows session. It uses your signed-in GitHub account, creates the public `sure2-rover` repository, pushes only manifest-listed files, verifies the remote commit, enables Pages from `main /docs`, and prints the links. If needed, first run `gh auth login --hostname github.com --web`. The publisher checks package hashes, enables size hooks, stops on errors and never force-pushes. It does not publish the parent college repository. This network workflow could not be exercised in the restricted development session; a printed verified result requires an actual successful deployment.

Manual alternative:

1. Create a **public** repository, for example `sure2-rover`. Upload this package's contents to its root on `main`, including the `docs` folder. Do not upload the ZIP as the only repository file.
2. Choose **Settings → Pages → Deploy from a branch → main → /docs → Save**.
3. When deployment completes, click **Visit site** and share that URL with the professor. Its usual form is `https://YOUR-ACCOUNT.github.io/sure2-rover/`.
4. The full source and launcher stay in the repository; only `docs` is the Pages site. Anyone who wants the local controller uses **Code → Download ZIP**, extracts it and runs SURE2.bat.

Nothing is already published by this package. No custom domain is required. GitHub Pages serves static HTML/JavaScript and cannot run the Python controller. References: [create a Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site), [choose a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) (checked 2026-10-07).

## Development and verification

Editable source: ContainmentIQ_Cabinet_Planner.html and preview/. Original source/schema names are retained for plan compatibility; team branding is sure². `python build_web_demo.py` rebuilds SURE2_Planner.html, github-pages and docs. Do not edit generated copies directly.

Python tests: `SURE2.bat Test`. Full browser suite: install Node.js, run `npm ci`, `npx playwright install chromium`, then `.venv\Scripts\python.exe run_e2e.py`. This uses private simulator servers. Reports are under e2e_results and browser-validation, excluded from the public repository package. Source tests cover keyboard combinations, release/STOP, focus loss, stale commands, reconnect/rearm, 2D/3D coordinates, camera controls, timing and plan export/import. Simulation success is not physical validation.

For a new Git clone, enable the bundled safeguards: `git config core.hooksPath .githooks`, `git config pull.ff only`, `git config pull.rebase false`. Never add a file of 100,000,000 bytes or larger. Logs, environments, dependencies, original downloads and personal course material are not included in this package. Three.js is bundled under its included MIT license; no license for other project material is implied.
