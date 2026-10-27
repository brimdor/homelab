#!/usr/bin/env python3
"""Build the stylesheet overlay from the exact retained production frontend."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


INPUTS = {
    'index.html': '2a50f18797500a324682f4c41a5c628b7cdd9dd529a0474ef9510c33e88c7134',
    'preferences.html': '924042d3b64db66c8e02921467e9dfe1973bc951c83ac06ab333841a180aa13c',
    'app.js': '53fd5186e079b97e905af1633bf01597cffa74349916f2a016c1e485020e1bf1',
    'countries.js': '0088f6c76f5bd2b9d0d4182cd16297f65c69122a8e17aa9d8d72ed7c9358eaef',
    'form.js': 'ab1715fc6b4f969d9cab6c43fa68a2432a36b5af2f4f5ec4c629a1d66db4ce33',
}
# Official v3.4.17 standalone macOS arm64 release, reviewed with this overlay.
COMPILER_SHA256 = 'a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3'
CSS_SHA256 = 'c7db6366c7ea056569b687753c71eb6d654d3a294318d7d375c1f204b637567c'


def build(source, compiler, output):
    if hashlib.sha256(compiler.read_bytes()).hexdigest() != COMPILER_SHA256:
        raise ValueError('reviewed Tailwind v3.4.17 compiler identity differs')
    inputs = {name: (source / name).read_bytes() for name in INPUTS}
    if any(hashlib.sha256(value).hexdigest() != INPUTS[name] for name, value in inputs.items()):
        raise ValueError('original production frontend identity differs')
    with tempfile.TemporaryDirectory(prefix='sporecast-frontend-styles-') as directory:
        work = Path(directory)
        for name, value in inputs.items():
            (work / name).write_bytes(value)
        config = work / 'tailwind.config.cjs'
        config.write_text('module.exports = ' + json.dumps({
            'darkMode': 'class', 'content': [str(work / '*.html'), str(work / '*.js')],
        }) + ';\n')
        css = work / 'input.css'
        css.write_text('@tailwind base;\n@tailwind components;\n@tailwind utilities;\n')
        stylesheet = work / 'styles.css'
        subprocess.run([str(compiler.resolve()), '-c', str(config), '-i', str(css),
                        '-o', str(stylesheet), '--minify'], check=True)
        compiled = stylesheet.read_bytes().rstrip(b'\n') + b'\n'
        if hashlib.sha256(compiled).hexdigest() != CSS_SHA256:
            raise ValueError('compiled stylesheet differs from the reviewed artifact')
        patches = {'styles.css': compiled}
        for name in ('index.html', 'preferences.html'):
            text = inputs[name].decode()
            script = '<script src="https://cdn.tailwindcss.com"></script>'
            setting = "    tailwind.config = { darkMode: 'class' };\n"
            if text.count(script) != 1 or text.count(setting) != 1:
                raise ValueError('original CDN or theme configuration differs')
            patches[name] = text.replace(script, '<link rel="stylesheet" href="/styles.css">').replace(setting, '').encode()
        output.mkdir(parents=True, exist_ok=True)
        for name, value in patches.items():
            (output / name).write_bytes(value)
    return {name: hashlib.sha256(value).hexdigest() for name, value in patches.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Original image static asset directory')
    parser.add_argument('--tailwind', type=Path, required=True, help='Reviewed standalone compiler executable')
    parser.add_argument('--output', type=Path, required=True, help='Directory for the three overlay files')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.tailwind, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
