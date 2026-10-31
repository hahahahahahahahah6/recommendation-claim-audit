"""Offline fresh-environment verification of both release artifacts."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd, expected=0):
    result = subprocess.run([str(x) for x in command], cwd=cwd, text=True, capture_output=True)
    assert result.returncode == expected, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout.strip()


def verify():
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        projects = work / 'projects'
        projects.mkdir()
        for name, doc, source, filename in [
            ('good', 'recommendations', 'from surprise import SVD\nSVD()', 'app.py'),
            ('bad', 'recommendations', 'sorted([])', 'app.py'),
            ('testonly', 'recommendations', 'from lightfm import LightFM\nLightFM()', 'tests/model.py'),
            ('negative', 'no recommendations', 'from implicit import als\nals.AlternatingLeastSquares()', 'app.py'),
        ]:
            project = projects / name
            project.mkdir()
            (project / 'README.md').write_text(doc)
            source_path = project / filename
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(source)
        for index, artifact in enumerate(sorted((ROOT / 'dist').iterdir())):
            env = work / ('venv' + str(index))
            run(['python3', '-m', 'venv', env], work)
            executable = env / 'bin/python3'
            # Seed build tools from this machine, without network access.
            site = Path(run([executable, '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], work))
            for pattern in ['setuptools', 'setuptools-*.egg-info', 'pkg_resources', '_distutils_hack', 'distutils-precedence.pth', 'wheel', 'wheel-*.egg-info', 'wheel-*.dist-info', 'setuptools-*.dist-info']:
                for source in Path('/usr/lib/python3/dist-packages').glob(pattern):
                    target = site / source.name
                    if source.is_dir():
                        shutil.copytree(source, target)
                    else:
                        shutil.copy2(source, target)
            run([executable, '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-build-isolation', artifact], work)
            for command in [[env / 'bin/recommendation-claim-audit'], [executable, '-m', 'recommendation_claim_audit']]:
                assert run(command + ['--version'], work) == '0.1.0'
                assert run(command + [projects / 'good'], work) == 'PASS'
                for name, rule, severity, code in [
                    ('bad', 'documented-recommendation-claim-false', 'HIGH', 2),
                    ('testonly', 'documented-recommendation-claim-false', 'MEDIUM', 0),
                    ('negative', 'documented-no-recommendation-claim-false', 'HIGH', 2),
                ]:
                    result = json.loads(run(command + [projects / name, '--json'], work, code))
                    assert len(result['findings']) == 1
                    finding = result['findings'][0]
                    assert (finding['rule_id'], finding['severity']) == (rule, severity)
                run(command + [projects / 'testonly', '--fail-on', 'MEDIUM'], work, 2)
                assert run(command + [ROOT], work) == 'PASS'
            print(artifact.name + ': all smoke checks PASS (both entry points)')


if __name__ == '__main__':
    verify()
