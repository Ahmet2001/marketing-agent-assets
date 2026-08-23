#!/usr/bin/env python3
"""Split an extracted MarketingApp toolbox into API and browser modules.

The original modules contain both official-API and Selenium actions. This
script preserves only the transitive function dependencies required by each
mode. API output intentionally excludes Selenium and shared-browser imports.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def names_used(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}


def is_selenium_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.startswith('selenium') for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return node.level > 0 or str(node.module or '').startswith('selenium')
    return False


def render_module(source_path: Path, destination: Path, mode: str) -> None:
    source = source_path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]

    if mode == 'api':
        selected = {name for name in functions if 'api' in name.casefold()}
    else:
        selected = {name for name in functions if not name.startswith('_') and 'api' not in name.casefold()}

    pending = list(selected)
    while pending:
        name = pending.pop()
        node = functions.get(name)
        if not node:
            continue
        for dependency in names_used(node):
            if dependency in functions and dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)

    imports: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if mode == 'api' and is_selenium_import(node):
                continue
            imports.append(node)
        elif isinstance(node, ast.Try) and any(isinstance(child, (ast.Import, ast.ImportFrom)) for child in ast.walk(node)):
            if mode != 'api' or not any(is_selenium_import(child) for child in ast.walk(node)):
                imports.append(node)

    chunks = [
        '"""Generated {mode} surface from the original MarketingApp toolbox.\n\n'
        'Do not mix browser and API actions in a worker process.\n"""'.format(mode=mode),
        'from __future__ import annotations'
    ]
    for node in imports:
        text = ast.unparse(node)
        if mode == 'browser':
            text = text.replace('from ..araclar.browser_araclari import', 'from MarketingApp.araclar.browser_araclari import')
        chunks.append(text)
    # Registries in the original module may reference actions from the other
    # mode (for example X_TOOLS). Do not carry a mixed registry into either
    # split module.
    def is_mixed_registry(node: ast.AST) -> bool:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(target, ast.Name) and (target.id.endswith('_TOOLS') or target.id == '__all__')
            for target in targets
        )

    retained_assignments = [
        node for node in assignments
        if not is_mixed_registry(node)
        and (not (names_used(node) & set(functions)) or (names_used(node) & set(functions)) <= selected)
    ]
    pre_function_assignments = [node for node in retained_assignments if not (names_used(node) & selected)]
    post_function_assignments = [node for node in retained_assignments if names_used(node) & selected]
    chunks.extend(ast.unparse(node) for node in pre_function_assignments)
    chunks.extend(ast.unparse(node) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected)
    chunks.extend(ast.unparse(node) for node in post_function_assignments)
    destination.write_text('\n\n'.join(chunks) + '\n', encoding='utf-8')


def main() -> None:
    for platform in ('x', 'instagram', 'reddit', 'youtube', 'tiktok'):
        directory = ROOT / 'toolboxes' / platform
        legacy = directory / 'legacy_combined_toolbox.py'
        if not legacy.exists():
            (directory / 'toolbox.py').rename(legacy)
        render_module(legacy, directory / 'api' / 'toolbox.py', 'api')
        render_module(legacy, directory / 'browser' / 'toolbox.py', 'browser')
        (directory / 'api' / '__init__.py').write_text('', encoding='utf-8')
        (directory / 'browser' / '__init__.py').write_text('', encoding='utf-8')
        (directory / 'toolbox.py').write_text(
            '"""Compatibility entry point for official API actions."""\n\nfrom .api.toolbox import *  # noqa: F401,F403\n',
            encoding='utf-8'
        )


if __name__ == '__main__':
    main()
