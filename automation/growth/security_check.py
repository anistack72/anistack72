"""Bounded source/config secret and supply-chain checks; not a full secret scanner."""
import re
from pathlib import Path


def check(root):
    findings = []
    tokens = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    for path in Path(root).rglob('*'):
        if not path.is_file() or any(p in path.parts for p in ('.git', '__pycache__', 'var', 'reports', 'evidence')):
            continue
        if path.suffix not in ('.py', '.md', '.json', '.yml', '.yaml', '.sh', '.toml'):
            continue
        text = path.read_text()
        if tokens.search(text):
            findings.append(str(path) + ': possible credential; value omitted')
        if path.suffix in ('.yml', '.yaml'):
            for line in text.splitlines():
                if re.search(r'\buses:', line) and not re.search(r'@[0-9a-f]{40}(?:\s|$)', line):
                    findings.append(str(path) + ': action must be SHA pinned')
    return findings


if __name__ == '__main__':
    errors = check('.')
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))
