# sure² planner demo

Open index.html in Chrome or Edge. It embeds the 3D scripts and works when copied alone. No Python, rover or network connection is needed for local planning and 3D playback.

Use Edit 2D for XY stations and Z heights, Preview 3D for playback, and Debug controller to open the remote interface directly. The static remote stays disabled without its Python server. All coordinates are millimeters. Right-click a station for Change / Direction / Delete; arrows nudge 5 mm (Shift: 1 mm). Settings contains geometry, timing, the optional table, and plan import/export. Export Complete plan JSON before refreshing to preserve edits.

The default is 2 rows by 6 stations, with 3 heights each: 12 stops and 36 planned targets. S6 and S7 turn left 90 degrees. Forward/backward/turn presets affect the preview only; inconsistent fixed presets are flagged. No physical controller sequence is executed.

The 3D cabinet and rover are nominal proxies; the lift/probe are concept placeholders. Actual geometry and clearance await measurement. Default preview assumptions: nonzero lift/park 20 s, travel 3 s, pivot 3 s per 90 degrees, settle 1.25 s and dwell 2.5 s. At 1x the complete default preview takes 894 s; zero-distance lift phases are skipped. Dwelling is not sensor acquisition. Default playback is 5x (about 2:59 on screen). For quick viewing choose 30x/60x, Next station or drag the timeline. The original supplied preview is restored: Perspective, Top, Front and Side retain free orbit/zoom; Reset view restores its camera. Visible components toggles shell, grid, route, height markers and rover/lift. Editing stays in 2D.

## Publish for teammates

1. Create a separate GitHub repository, for example sure2-planner.
2. Upload ALL contents of this folder to its root, preserving directories: index.html, debug.html, .nojekyll, README.md, and the complete preview folder (scene.js, assets.js, THREE-LICENSE.txt, vendor/three.min.js).
3. In repository Settings > Pages, select Deploy from a branch, main, /(root), then Save.
4. After deployment completes, use Visit site and share that URL. No site has been published by this work.

The bundle is below 2 MB; each file is below GitHub's 100 MB limit. The supplied source ZIP, Python environment, runtime logs and course files are not needed on the public site. Three.js is bundled with its MIT license. GitHub Pages hosts the static planner; it cannot run Python or communicate through the local controller backend. The Debug tab shows the remote UI disabled and links directly to the local Python controller. Nothing has been published automatically.

Publishing reference: [GitHub publishing-source instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site), checked 2026-10-07. Branch publishing uses repository root or /docs, not an arbitrary nested course folder.

## Update

From the full kit, run `.\.venv\Scripts\python.exe build_web_demo.py`, then `.\.venv\Scripts\python.exe -u run_e2e.py`. Publish the entire regenerated folder, including changed JavaScript assets. The build removes the local Python handoff and preserves the shared coordinate/timing logic. For an integrated local simulator, run START_SIMULATOR.bat and open http://127.0.0.1:8765/.

Use the top Timing button to edit settling and dwelling. Apply dwell to all stations updates the complete route; imported plans preserve their saved timing. The full repository package includes SURE2.bat and publishes this site from /docs.
