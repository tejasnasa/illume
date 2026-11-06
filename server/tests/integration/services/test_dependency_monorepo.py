"""Dependency edges in a monorepo whose apps reuse the same tsconfig alias.

Two apps that both map ``@/*`` to their own ``src/`` and contain files with the
same relative paths: every ``@/`` import must land in the importer's own app.
When the aliases were merged into one map, one app's imports all crossed into
the other, fusing the two apps into a single cluster in the dependency graph.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.models import AstSymbol, Dependency, File
from app.services.dependency_resolver import resolve_dependencies
from tests.factories import make_file, make_repo, make_symbol, make_user

pytestmark = pytest.mark.integration

APPS = ("client", "mobile")


async def test_each_apps_alias_imports_stay_inside_that_app(db_session, tmp_path):
    for app in APPS:
        config = tmp_path / app / "tsconfig.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}))

    repo = await make_repo(db_session, await make_user(db_session))
    for app in APPS:
        target = await make_file(
            db_session, repo, path=f"{app}/src/lib/apiError.ts", language="typescript"
        )
        await make_symbol(db_session, target, name="ApiError", kind="class")
        importer = await make_file(
            db_session, repo, path=f"{app}/src/api/client.ts", language="typescript"
        )
        await make_symbol(db_session, importer, name="@/lib/apiError", kind="import")
        await make_symbol(db_session, importer, name="request")

    inserted = await db_session.run_sync(
        lambda session: resolve_dependencies(session, repo.id, str(tmp_path))
    )

    source_file, target_file = aliased(File), aliased(File)
    source_symbol, target_symbol = aliased(AstSymbol), aliased(AstSymbol)
    rows = (
        await db_session.execute(
            select(source_file.path, target_file.path)
            .select_from(Dependency)
            .join(source_symbol, Dependency.source_symbol_id == source_symbol.id)
            .join(source_file, source_symbol.file_id == source_file.id)
            .join(target_symbol, Dependency.target_symbol_id == target_symbol.id)
            .join(target_file, target_symbol.file_id == target_file.id)
            .where(source_file.repository_id == repo.id)
        )
    ).all()

    assert inserted == 2
    assert sorted(rows) == [
        ("client/src/api/client.ts", "client/src/lib/apiError.ts"),
        ("mobile/src/api/client.ts", "mobile/src/lib/apiError.ts"),
    ]
