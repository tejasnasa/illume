"""Import specifier resolution.

`resolve_import` turns a raw specifier into a repo-relative path stem, or None when the
import points outside the repository. The None cases matter as much as the hits: a bare
`react` import mistaken for an internal path fabricates a dependency edge to a file that
does not exist.
"""

import json

import pytest

from app.services.import_resolver import (
    load_ts_paths,
    load_workspace_map,
    resolve_import,
)

pytestmark = pytest.mark.unit


def write(path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class TestGuards:
    @pytest.mark.parametrize("specifier", ["", "<anonymous>"])
    def test_ignores_placeholder_specifiers(self, specifier, tmp_path):
        assert resolve_import("python", specifier, "a.py", str(tmp_path)) is None

    def test_none_specifier_is_ignored(self, tmp_path):
        assert resolve_import("python", None, "a.py", str(tmp_path)) is None


class TestPython:
    def test_absolute_dotted_import_becomes_a_path(self, tmp_path):
        resolved = resolve_import("python", "app.core.config", "main.py", str(tmp_path))

        assert resolved == "app/core/config"

    def test_plain_module_name(self, tmp_path):
        assert resolve_import("python", "utils", "main.py", str(tmp_path)) == "utils"

    def test_aliased_import_is_reduced_to_the_module(self, tmp_path):
        resolved = resolve_import("python", "app.models as models", "main.py", str(tmp_path))

        assert resolved == "app/models"

    def test_single_dot_relative_import(self, tmp_path):
        resolved = resolve_import("python", ".sibling", "pkg/module.py", str(tmp_path))

        assert resolved == "pkg/sibling"

    def test_double_dot_relative_import_climbs_one_directory(self, tmp_path):
        resolved = resolve_import("python", "..utils", "app/api/routes.py", str(tmp_path))

        assert resolved == "app/utils"

    def test_triple_dot_climbs_two_directories(self, tmp_path):
        resolved = resolve_import("python", "...deep", "a/b/c/mod.py", str(tmp_path))

        assert resolved == "a/deep"

    def test_bare_relative_import_points_at_the_package(self, tmp_path):
        """`from . import x` yields the package directory itself."""
        resolved = resolve_import("python", ".", "pkg/module.py", str(tmp_path))

        assert resolved == "pkg"

    def test_relative_import_with_dotted_remainder(self, tmp_path):
        resolved = resolve_import("python", ".sub.thing", "pkg/module.py", str(tmp_path))

        assert resolved == "pkg/sub/thing"


class TestJavaScriptRelative:
    def test_sibling_file(self, tmp_path):
        resolved = resolve_import("typescript", "./utils", "src/index.ts", str(tmp_path))

        assert resolved == "src/utils"

    def test_parent_traversal_is_normalized(self, tmp_path):
        resolved = resolve_import(
            "typescript", "../lib/helpers", "src/deep/index.ts", str(tmp_path)
        )

        assert resolved == "src/lib/helpers"

    def test_traversal_above_the_root_does_not_escape(self, tmp_path):
        """
        Popping an empty stack is a no-op, so an over-deep `../..` cannot produce a
        leading `/` or escape the repository.
        """
        resolved = resolve_import("typescript", "../../../../etc/passwd", "index.ts", str(tmp_path))

        assert not resolved.startswith("/")
        assert ".." not in resolved

    def test_current_directory_prefix_is_dropped(self, tmp_path):
        resolved = resolve_import("javascript", "./deep/./thing", "src/index.js", str(tmp_path))

        assert resolved == "src/deep/thing"


class TestJavaScriptExternal:
    @pytest.mark.parametrize(
        "specifier",
        ["react", "next/router", "lodash/fp", "@scope/pkg", "@scope/pkg/sub"],
    )
    def test_bare_packages_resolve_to_nothing(self, specifier, tmp_path):
        """External dependencies must not fabricate internal edges."""
        resolved = resolve_import("typescript", specifier, "src/index.ts", str(tmp_path))

        assert resolved is None


class TestTsConfigAliases:
    def test_alias_from_tsconfig_is_applied(self, tmp_path):
        write(
            tmp_path / "tsconfig.json",
            {"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}},
        )
        ts_paths = load_ts_paths(tmp_path)

        resolved = resolve_import(
            "typescript", "@/components/Button", "src/app/page.tsx", str(tmp_path), ts_paths
        )

        assert resolved == "src/components/Button"

    def test_alias_map_is_loaded_with_wildcards_stripped(self, tmp_path):
        write(
            tmp_path / "tsconfig.json",
            {"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}},
        )

        # The target is a resolved filesystem path, so it carries no trailing slash.
        # Matching works by prefix; `_resolve_ts_alias` joins with Path().
        assert load_ts_paths(tmp_path) == {"@/": "src"}

    def test_node_modules_tsconfig_is_ignored(self, tmp_path):
        write(
            tmp_path / "node_modules" / "dep" / "tsconfig.json",
            {"compilerOptions": {"paths": {"#/*": ["./lib/*"]}}},
        )

        assert load_ts_paths(tmp_path) == {}

    def test_unresolvable_alias_falls_through_to_none(self, tmp_path):
        """An alias map that does not match leaves a bare specifier external."""
        resolved = resolve_import(
            "typescript", "@/thing", "src/index.ts", str(tmp_path), {"$": "src/"}
        )

        assert resolved is None

    def test_malformed_tsconfig_is_skipped(self, tmp_path):
        write(tmp_path / "tsconfig.json", "this is not json{")

        assert load_ts_paths(tmp_path) == {}

    def test_jsconfig_is_also_read(self, tmp_path):
        write(
            tmp_path / "jsconfig.json",
            {"compilerOptions": {"baseUrl": ".", "paths": {"~/*": ["./lib/*"]}}},
        )

        assert load_ts_paths(tmp_path) == {"~/": "lib"}


class TestWorkspaceMap:
    def test_scoped_package_with_root_export_is_mapped(self, tmp_path):
        write(
            tmp_path / "packages" / "ui" / "package.json",
            {
                "name": "@acme/ui",
                "exports": {".": {"import": "./src/index.ts"}},
            },
        )
        workspace_map = load_workspace_map(str(tmp_path))

        assert workspace_map["@acme/ui"] == "packages/ui/src/index"

    def test_subpath_import_resolves_through_the_prefix_entry(self, tmp_path):
        write(
            tmp_path / "packages" / "ui" / "package.json",
            {"name": "@acme/ui", "exports": {".": {"import": "./src/index.ts"}}},
        )
        workspace_map = load_workspace_map(str(tmp_path))

        resolved = resolve_import(
            "typescript",
            "@acme/ui/button",
            "apps/web/src/page.tsx",
            str(tmp_path),
            workspace_map=workspace_map,
        )

        assert resolved == "packages/ui/src/button"

    def test_dist_main_is_rewritten_to_src(self, tmp_path):
        write(
            tmp_path / "packages" / "core" / "package.json",
            {"name": "@acme/core", "main": "./dist/index.js"},
        )
        workspace_map = load_workspace_map(str(tmp_path))

        assert workspace_map["@acme/core"] == "packages/core/src/index"

    def test_longest_prefix_wins(self, tmp_path):
        """`@acme/ui-kit` must not be shadowed by a `@acme/ui` entry."""
        write(
            tmp_path / "packages" / "ui" / "package.json",
            {"name": "@acme/ui", "exports": {".": {"import": "./src/index.ts"}}},
        )
        write(
            tmp_path / "packages" / "ui-kit" / "package.json",
            {"name": "@acme/ui-kit", "exports": {".": {"import": "./src/index.ts"}}},
        )
        workspace_map = load_workspace_map(str(tmp_path))

        assert "@acme/ui-kit/" in workspace_map
        assert "@acme/ui-kit" in workspace_map

    def test_node_modules_packages_are_ignored(self, tmp_path):
        write(
            tmp_path / "node_modules" / "dep" / "package.json",
            {"name": "@external/dep", "main": "./index.js"},
        )
        workspace_map = load_workspace_map(str(tmp_path))

        assert "@external/dep" not in workspace_map

    def test_nameless_package_json_is_skipped(self, tmp_path):
        write(tmp_path / "package.json", {"private": True})

        assert load_workspace_map(str(tmp_path)) == {}


class TestJava:
    def test_class_import_becomes_a_java_path(self, tmp_path):
        resolved = resolve_import(
            "java", "com.example.service.UserService", "Main.java", str(tmp_path)
        )

        assert resolved == "com/example/service/UserService.java"

    def test_wildcard_import_drops_the_star(self, tmp_path):
        resolved = resolve_import("java", "com.example.service.*", "Main.java", str(tmp_path))

        assert resolved == "com/example/service.java"

    def test_constant_import_drops_the_member_segment(self, tmp_path):
        """`import a.b.MAX_RETRIES` names a constant, so the path is the class file."""
        resolved = resolve_import(
            "java", "com.example.Constants.MAX_RETRIES", "Main.java", str(tmp_path)
        )

        assert resolved == "com/example/Constants.java"

    def test_lowercase_trailing_segment_is_treated_as_a_member(self, tmp_path):
        resolved = resolve_import(
            "java", "com.example.Service.instance", "Main.java", str(tmp_path)
        )

        assert resolved == "com/example/Service.java"

    def test_a_single_segment_is_unresolvable(self, tmp_path):
        assert resolve_import("java", "UserService", "Main.java", str(tmp_path)) is None


class TestGeneric:
    def test_bare_word_is_unresolvable(self, tmp_path):
        assert resolve_import("ruby", "thing", "main.rb", str(tmp_path)) is None

    def test_dotted_name_becomes_a_path(self, tmp_path):
        resolved = resolve_import("csharp", "My.Namespace.Thing", "Program.cs", str(tmp_path))

        assert resolved == "My/Namespace/Thing"

    def test_relative_path_is_normalized(self, tmp_path):
        resolved = resolve_import("go", "../pkg/util", "cmd/app/main.go", str(tmp_path))

        assert resolved == "cmd/pkg/util"

    def test_quotes_are_stripped(self, tmp_path):
        resolved = resolve_import("ruby", '"lib/thing"', "main.rb", str(tmp_path))

        assert resolved == "lib/thing"
