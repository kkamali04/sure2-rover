"""Build an offline static planner bundle, including local 3D assets; no hardware backend."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent


def standalone(source):
    """Inline pinned local scripts so a copied HTML file keeps its 3D viewer."""
    for name in ('preview/vendor/three.min.js', 'preview/assets.js', 'preview/scene.js'):
        script = (ROOT / name).read_text(encoding='utf-8').replace('</script', r'<\/script')
        tag = f'<script src="{name}"></script>'
        if tag not in source:
            raise ValueError(f'Missing expected asset: {name}')
        source = source.replace(tag, f'<script>\n{script}\n</script>')
    license_text = (ROOT / 'preview/vendor/THREE-LICENSE.txt').read_text(encoding='utf-8')
    return source.replace('</head>', '<!-- Bundled Three.js license:\n' + license_text + '\n--></head>')


def main():
    source = (ROOT / 'ContainmentIQ_Cabinet_Planner.html').read_text(encoding='utf-8')
    (ROOT / 'SURE2_Planner.html').write_text(standalone(source), encoding='utf-8')
    # Strip the local Python handoff from the public copy, retaining the planner.
    lines = source.splitlines()
    handoff = [line for line in lines if "$('handoffBtn').addEventListener" in line]
    if len(handoff) != 1:
        raise ValueError('Planner handoff changed; review the static build before publishing.')
    source = source.replace(handoff[0], '')
    source = source.replace('<button id="handoffBtn">Use this design in controller test</button>', '')
    source = source.replace('Save, import or hand off', 'Save or import your plan')
    source = source.replace(
        'Downloads are explicit. The controller handoff button saves the plan to your local Python session when opened from its planner link. It sends no rover commands. File exports also work offline. Use the separate bench-test script for bounded manual jogs after verification.',
        'Download Complete plan JSON to keep your edits or share them with a teammate. Import that JSON to continue later. Changes stay in this page until you download them; refreshing resets the example. The separate local Python controller can import the same plan.')
    source = source.replace('Local prototype · v0.1', 'Interactive planning demo · v0.1')
    source = source.replace('OFFLINE / NO CONNECTION', 'BROWSER DEMO / NO ROVER')
    source = source.replace('href="/debug"', 'href="debug.html"')
    if 'fetch(' in source or 'handoffBtn' in source:
        raise ValueError('Unexpected backend dependency in static demo.')
    output = ROOT / 'github-pages'
    output.mkdir(exist_ok=True)
    (output / 'index.html').write_text(standalone(source), encoding='utf-8')
    (output / '.nojekyll').write_text('', encoding='utf-8')
    shutil.copytree(ROOT / 'preview', output / 'preview', dirs_exist_ok=True)
    # The static tab opens the real remote UI, disabled without its Python backend.
    remote = (ROOT / 'remote_controller.html').read_text(encoding='utf-8')
    remote = remote.replace("const allowedOrigin=location.protocol==='http:'&&['127.0.0.1','localhost'].includes(location.hostname);", 'const allowedOrigin=false; // Static copy: no backend requests.')
    remote = remote.replace('href="/">Edit 2D', 'href="index.html">Edit 2D')
    remote = remote.replace('<script src="/validation_panel.js"></script>', '<script>document.getElementById("validationPanel").hidden=true;</script>')
    (output / 'debug.html').write_text(remote, encoding='utf-8')
    (ROOT / 'debug.html').write_text(remote.replace('href="index.html">Edit 2D', 'href="SURE2_Planner.html">Edit 2D'), encoding='utf-8')
    # The clean repository package publishes its /docs folder through Pages.
    if (ROOT / 'docs').is_dir():
        shutil.copytree(output, ROOT / 'docs', dirs_exist_ok=True)
    print(f'Built {output / "index.html"} ({(output / "index.html").stat().st_size:,} bytes; standalone)')


if __name__ == '__main__':
    main()
