import os
import pathlib
import subprocess
import re


def get_head_info():
    backend_path = pathlib.Path(__file__).parents[1]
    os.chdir(backend_path)

    result = subprocess.run(['git', 'rev-parse', 'HEAD'], stdout=subprocess.PIPE)
    sha = result.stdout.decode('utf-8').strip()

    result = subprocess.run(['git', 'show', '--no-patch', '--format="%cd"', '--date=short', sha], stdout=subprocess.PIPE)
    date = result.stdout.decode('utf-8').strip()

    m = re.match(r'^"(.+)"$', date)
    date = m.group(1)

    return dict(sha = sha, date = date)
