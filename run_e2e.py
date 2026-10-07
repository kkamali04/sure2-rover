"""Run and archive software E2E checks. Uses simulated/fake transports only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    output = ROOT / 'e2e_results' / stamp
    output.mkdir(parents=True)
    env = dict(os.environ, PYTHON=sys.executable, ROVER_TEST_PYTHON=sys.executable)
    commands = [
        ('python', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']),
        ('remote_ui', ['node', 'tests/test_remote_ui.cjs']),
        ('planner_core', ['node', 'tests/test_planner_core.cjs']),
        ('planner_dom', ['node', 'tests/test_planner_dom.cjs']),
        ('planner_dashboard', ['node', 'tests/test_planner_dashboard.cjs']),
        ('browser_e2e', ['node', 'tests/test_remote_browser.cjs']),
    ]
    checks = []
    for name, command in commands:
        print(f'Running {name}...', flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                    encoding='utf-8', errors='replace', timeout=180)
            text = result.stdout + result.stderr
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            text, code = str(error), 1
        (output / f'{name}.log').write_text(text, encoding='utf-8')
        checks.append(dict(check=name, exit_code=code, passed=code == 0))
        print(text, flush=True)
        if code:
            break
    browser_output = ROOT / 'browser-validation'
    if browser_output.exists():
        shutil.copytree(browser_output, output / 'browser-validation')
    report = dict(time=datetime.now(timezone.utc).isoformat(), checks=checks,
                  all_passed=len(checks) == len(commands) and all(c['passed'] for c in checks),
                  scope='Software E2E with simulated/fake rover; no physical motion, localization, lift or sensor certification.')
    (output/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Report saved: {output}', flush=True)
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
