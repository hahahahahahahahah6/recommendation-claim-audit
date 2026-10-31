"""Static documentation and source analysis; source is never executed."""
import ast
import os
import re
import tokenize
from pathlib import Path
from .phrases import RECOMMENDATION, NORECOMMENDATION

SURPRISE = {'SVD', 'SVDpp', 'KNNBasic', 'KNNWithMeans', 'KNNBaseline', 'NMF', 'CoClustering'}
IMPLICIT = {'AlternatingLeastSquares', 'BayesianPersonalizedRanking', 'LogisticMatrixFactorization', 'CosineRecommender', 'TFIDFRecommender', 'BM25Recommender', 'ItemItemRecommender'}


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def prose(text):
    lines = []
    fence = None
    for line in text.splitlines():
        if fence:
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', line):
                fence = None
            lines.append('')
            continue
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if match and not (match[1][0] == '`' and '`' in match[2]):
            fence = (match[1][0], len(match[1]))
            lines.append('')
        else:
            lines.append(line)
    return re.split(r'\n\s*\n', '\n'.join(lines))


def match_phrases(text, phrases):
    pattern = r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=lambda p: (-len(p), p))) + r')\b'
    return list(re.finditer(pattern, text))


def claims(text):
    positive, negative = set(), set()
    for paragraph in prose(text):
        paragraph = normalize(paragraph)
        matches = match_phrases(paragraph, NORECOMMENDATION)
        negative.update(m.group() for m in matches)
        for m in reversed(matches):
            paragraph = paragraph[:m.start()] + ' ' * (m.end() - m.start()) + paragraph[m.end():]
        positive.update(m.group() for m in match_phrases(paragraph, RECOMMENDATION))
    return sorted(positive), sorted(negative)


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    aliases, shadows = {}, set()
    # Bindings are deliberately module-local; imports never cross file boundaries.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = node.module + '.' + alias.name
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadows.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadows.add(node.id)
        elif isinstance(node, ast.arg):
            shadows.add(node.arg)
    def resolve(node):
        if isinstance(node, ast.Name):
            return None if node.id in shadows else aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else None
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolve(node.func)
        if not name:
            continue
        package, leaf = name.split('.')[0], name.split('.')[-1]
        if (package == 'surprise' and leaf in SURPRISE or
                package == 'lightfm' and leaf == 'LightFM' or
                package == 'implicit' and leaf in IMPLICIT):
            return True
    return False


def audit(root, ignores=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('root must be an existing, non-symlink directory')
    prefixes = []
    for item in ignores:
        path = Path(item)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('--ignore requires a relative path prefix without ..')
        prefixes.append(path.parts)
    def ignored(parts):
        return any(parts[:len(prefix)] == prefix for prefix in prefixes)
    positive, negative, production, tests = [], [], [], []
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink() and not ignored((base / d).relative_to(root).parts))
        for filename in sorted(files):
            path = base / filename
            rel = path.relative_to(root)
            if path.is_symlink() or ignored(rel.parts):
                continue
            if filename.endswith('.md') and (rel.as_posix() == 'README.md' or 'docs' in rel.parts[:-1]):
                pos, neg = claims(path.read_text(encoding='utf-8'))
                positive.extend({'path': rel.as_posix(), 'phrase': p} for p in pos)
                negative.extend({'path': rel.as_posix(), 'phrase': p} for p in neg)
            if path.suffix != '.py' or {'fixtures', 'docs', 'examples'} & set(rel.parts[:-1]):
                continue
            with tokenize.open(path) as stream:
                found = evidence(stream.read())
            if found:
                is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                (tests if is_test else production).append(rel.as_posix())
    findings = []
    if positive and not production:
        findings.append({'rule_id': 'documented-recommendation-claim-false', 'severity': 'MEDIUM' if tests else 'HIGH', 'claims': positive, 'message': 'Evidence exists only in tests.' if tests else 'No production evidence found.'})
    if negative and production:
        findings.append({'rule_id': 'documented-no-recommendation-claim-false', 'severity': 'HIGH', 'claims': negative, 'message': 'Production evidence contradicts the documented claim.'})
    return {'status': 'FAIL' if findings else 'PASS', 'findings': findings, 'evidence': {'production': sorted(production), 'tests': sorted(tests)}}
