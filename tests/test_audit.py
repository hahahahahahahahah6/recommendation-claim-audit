import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from recommendation_claim_audit.audit import audit, claims, evidence, SURPRISE, IMPLICIT, match_phrases
from recommendation_claim_audit.phrases import RECOMMENDATION, NORECOMMENDATION
from recommendation_claim_audit.__main__ import main


class PhraseTests(unittest.TestCase):
    def test_negative_removal(self):
        self.assertEqual(claims('does not recommend items'), ([], ['does not recommend items']))
        self.assertEqual(claims('no recommendations; recommends movies'), (['recommends movies'], ['no recommendations']))

    def test_normalization(self):
        self.assertEqual(claims("DOESN'T recommend items"), ([], ['does not recommend items']))
        self.assertEqual(claims('personalized-\n recommendations'), (['personalized recommendations'], []))
        self.assertEqual(claims('personalized\n\n suggestions'), ([], []))

    def test_fences(self):
        for marker in ('```', '~~~', '   ````'):
            self.assertEqual(claims(marker + '\nrecommendations\n' + marker), ([], []))
        self.assertEqual(claims('`recommendations`'), (['recommendations'], []))
        self.assertEqual(claims('```py\nrecommendations'), ([], []))
        self.assertEqual(claims('~~~\n```\nrecommendations\n~~~'), ([], []))
        self.assertEqual(claims('    ```\nrecommendations'), (['recommendations'], []))


class EvidenceTests(unittest.TestCase):
    def test_non_evidence(self):
        cases = ["sorted(items, key=lambda x:x.popularity)", "sorted(items, key=lambda x:x.count)", "sorted(items, key=lambda x:x.rating)", "sorted(items, key=lambda x:x.recency)", "from sklearn.ensemble import RandomForestClassifier\nRandomForestClassifier()", "from sklearn.linear_model import LinearRegression\nLinearRegression()", "from sklearn.metrics.pairwise import cosine_similarity\ncosine_similarity(a,b)", "from sklearn.neighbors import NearestNeighbors\nNearestNeighbors().kneighbors(a)", "client.chat.completions.create(model='x')", "from surprise import Dataset\nDataset.load_builtin('x')", "from surprise import Dataset\nDataset.load_from_df(df, reader)", "import surprise", "from surprise import SVD\nSVD", "'surprise.SVD()'", "import subprocess\nsubprocess.run(['SVD()'])", "def SVD(): pass\nSVD()", "from other import SVD\nSVD()", "from lightfm import LightFM\nLightFM", "from implicit.als import AlternatingLeastSquares\nAlternatingLeastSquares", "from surprise import SVD\ndef SVD(): pass\nSVD()", "import surprise as s\ns = object()\ns.SVD()", "from surprise import SVD\nclass SVD: pass\nSVD()", "from surprise import SVD\nSVD = factory\nSVD()", "from surprise import SVD\ninvalid syntax !"]
        for source in cases:
            with self.subTest(source=source):
                self.assertFalse(evidence(source))

    def test_no_execution(self):
        self.assertTrue(evidence("raise RuntimeError('never execute')\nfrom surprise import SVD\nSVD()"))


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_no_source_asymmetry(self):
        self.put('README.md', 'recommendations')
        result = audit(self.root)
        self.assertEqual(result['findings'][0]['rule_id'], 'documented-recommendation-claim-false')
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertEqual(self.cli()[0], 2)
        self.put('README.md', 'no recommendations')
        self.assertEqual(audit(self.root)['status'], 'PASS')

    def test_negative_contradiction(self):
        self.put('README.md', 'no recommendations')
        self.put('app.py', 'from surprise import SVD\nSVD()')
        f = audit(self.root)['findings']
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]['rule_id'], f[0]['severity']), ('documented-no-recommendation-claim-false', 'HIGH'))
        self.assertEqual(self.cli()[0], 2)

    def test_testonly(self):
        self.put('README.md', 'recommendations')
        for name in ['tests/model.py', 'test_model.py', 'model_test.py']:
            path = self.put(name, 'from surprise import SVD\nSVD()')
            self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
            self.assertEqual(self.cli()[0], 0)
            self.assertEqual(self.cli('--fail-on', 'MEDIUM')[0], 2)
            path.unlink()

    def test_scopes(self):
        self.put('notes.md', 'recommendations')
        self.put('nested/README.md', 'recommendations')
        self.assertEqual(audit(self.root)['status'], 'PASS')
        self.put('nested/docs/deep/claims.md', 'recommendations')
        for name in ['fixtures/app.py', 'docs/app.py', 'examples/app.py']:
            self.put(name, 'from surprise import SVD\nSVD()')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')
        self.put('app.py', 'from surprise import SVD\nSVD()')
        self.assertEqual(audit(self.root)['status'], 'PASS')

    def test_aliases_do_not_cross_modules(self):
        self.put('README.md', 'recommendations')
        self.put('a.py', 'from surprise import SVD')
        self.put('b.py', 'SVD()')
        self.assertEqual(self.cli()[0], 2)

    def test_symlinks(self):
        self.put('README.md', 'recommendations')
        outside = self.root.parent / (self.root.name + '_outside')
        outside.mkdir()
        self.addCleanup(lambda: __import__('shutil').rmtree(outside))
        (outside / 'model.py').write_text('from surprise import SVD\nSVD()')
        (self.root / 'model.py').symlink_to(outside / 'model.py')
        (self.root / 'linked').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.cli()[0], 2)

    def test_json_verbose_ignore(self):
        self.put('README.md', 'recommendations')
        self.assertEqual(json.loads(self.cli('--json')[1])['findings'][0]['severity'], 'HIGH')
        self.assertIn('README.md: recommendations', self.cli('--verbose')[1])
        self.assertEqual(self.cli('--ignore', 'README.md')[0], 0)
        self.put('models/a.py', 'from surprise import SVD\nSVD()')
        self.assertEqual(self.cli()[0], 0)
        self.assertEqual(self.cli('--ignore', 'models')[0], 2)
        self.assertEqual(self.cli('--ignore', 'model')[0], 0)
        self.assertEqual(self.cli('--ignore', 'models', '--ignore', 'README.md')[0], 0)

    def test_errors_version(self):
        self.assertEqual(self.cli('--fail-on', 'INVALID')[0], 1)
        self.assertEqual(self.cli('--ignore', '../outside')[0], 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['--version']), 0)
        self.assertEqual(out.getvalue(), '0.1.0\n')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 1)
            self.assertEqual(main([str(self.root / 'absent')]), 1)
        self.put('README.md', 'x').write_bytes(b'\xff')
        self.assertEqual(self.cli()[0], 1)

    def test_self_audit(self):
        self.assertEqual(audit(Path(__file__).resolve().parents[1])['status'], 'PASS')


def phrase_test(phrase, negative):
    def test(self):
        self.assertEqual(claims(phrase), ([], [phrase]) if negative else ([phrase], []))
        self.assertEqual(match_phrases('prefix' + phrase + 'suffix', [phrase]), [])
    return test


for family, phrases in [('positive', RECOMMENDATION), ('negative', NORECOMMENDATION)]:
    for index, phrase in enumerate(phrases):
        setattr(PhraseTests, 'test_' + family + '_' + str(index), phrase_test(phrase, family == 'negative'))


def route_test(source):
    def test(self):
        self.assertTrue(evidence(source), source)
    return test


routes = []
for package, classes in [('surprise', SURPRISE), ('implicit.als', IMPLICIT), ('lightfm', {'LightFM'})]:
    for cls in sorted(classes):
        routes.extend([f'import {package}\n{package}.{cls}()', f'import {package} as lib\nlib.{cls}()', f'from {package} import {cls}\n{cls}()', f'from {package} import {cls} as Model\nModel()'])
routes += ['import implicit\nimplicit.als.AlternatingLeastSquares()', 'from implicit import als\nals.AlternatingLeastSquares()']
for index, source in enumerate(routes):
    setattr(EvidenceTests, 'test_route_' + str(index), route_test(source))
