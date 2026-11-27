"""A project's own import names are not dependencies (`census_aliases.py`).

`"@components/*": ["src/components/*"]` in a tsconfig makes `@components/Button` the
project's own file, though it is spelled like a scoped npm package. Until 2026-11-27 both
censuses reported such names: the imports census as undeclared dependencies, the
dependencies census as unresolved contracts, which cap every finding about them at
hypothesis. `baseUrl` does the same for a bare `components/Button`.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp.census import dependencies_census, imports_census  # noqa: E402
from verdict_mcp.census_aliases import names_own_files, read_config  # noqa: E402


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# What tsc accepts: comments, trailing commas, and a lone "*" that is a fallback, not an alias.
TSCONFIG = """{
  // tsc reads comments and trailing commas, so the census does too
  "compilerOptions": {
    "baseUrl": ".",
    /* a block comment, with "quotes" and a comma, */
    "paths": {
      "@components/*": ["src/components/*"],
      "@lib": ["src/lib/index.ts"],
      "*": ["types/*"],
    },
  },
}
"""

APP = [
    ("src/app.ts", 1, "import Button from '@components/Button'"),
    ("src/app.ts", 2, "import { lib } from '@lib'"),
    ("src/app.ts", 3, "import _ from 'lodash'"),
    ("src/app.ts", 4, "import real from '@scope/real'"),
    ("src/app.ts", 5, "import pad from 'left-pad'"),
]


def test_a_paths_alias_is_the_projects_own_file_in_both_censuses(tmp_path):
    write(tmp_path, "tsconfig.json", TSCONFIG)
    write(tmp_path, "package.json", json.dumps({"dependencies": {"lodash": "^4.17.0"}}))
    write(tmp_path, "node_modules/lodash/package.json",
          json.dumps({"name": "lodash", "version": "4.17.21"}))
    deps = dependencies_census(tmp_path, APP)
    assert sorted(deps["resolved"]) == ["lodash"]
    assert deps["unresolved"] == {"@scope/real": ["src/app.ts:4"],
                                  "left-pad": ["src/app.ts:5"]}
    assert "alias_configs_unreadable" not in deps
    assert sorted(imports_census(tmp_path, APP)["undeclared"]) == ["@scope/real", "left-pad"]


def test_a_base_url_import_is_the_projects_own_file(tmp_path):
    write(tmp_path, "jsconfig.json", '{"compilerOptions": {"baseUrl": "src"}}')
    write(tmp_path, "src/components/Button.jsx", "export default 1\n")
    write(tmp_path, "src/utils.js", "export const x = 1\n")
    out = dependencies_census(tmp_path, [
        ("src/App.jsx", 1, "import Button from 'components/Button'"),
        ("src/App.jsx", 2, "import { x } from 'utils'"),
        ("src/App.jsx", 3, "import React from 'react'")])
    assert out["unresolved"] == {"react": ["src/App.jsx:3"]}


def test_the_nearest_config_rules_and_its_own_paths_replace_what_it_extends(tmp_path):
    """A monorepo: each app's tsconfig extends the root's base. tsc picks the nearest
    tsconfig up the tree. A `paths` of the app's own replaces the base's, and a file under
    no tsconfig gets no aliases; the base alone is no config tsc reads."""
    write(tmp_path, "tsconfig.base.json",
          '{"compilerOptions": {"paths": {"@shared/*": ["libs/shared/*"]}}}')
    write(tmp_path, "apps/web/tsconfig.json", '{"extends": "../../tsconfig.base"}')
    write(tmp_path, "apps/api/tsconfig.json",
          '{"extends": ["../../tsconfig.base.json"],'
          ' "compilerOptions": {"paths": {"@api/*": ["src/*"]}}}')
    out = dependencies_census(tmp_path, [
        ("apps/web/src/page.ts", 1, "import { Card } from '@shared/ui'"),
        ("apps/api/src/route.ts", 1, "import { Card } from '@shared/ui'"),
        ("apps/api/src/route.ts", 2, "import { db } from '@api/db'"),
        ("tools/seed.ts", 1, "import { Card } from '@shared/ui'")])
    assert out["unresolved"] == {"@shared/ui": ["apps/api/src/route.ts:1", "tools/seed.ts:1"]}


def test_a_config_that_cannot_be_read_is_said_and_its_names_stay_unresolved(tmp_path):
    write(tmp_path, "tsconfig.json", '{"compilerOptions": {"paths": {"@components/*": ["src/*"]}')
    out = dependencies_census(tmp_path, APP[:1])
    assert out["unresolved"] == {"@components/Button": ["src/app.ts:1"]}, \
        "an unread config's names are unknown, not the project's own"
    assert out["alias_configs_unreadable"] == ["tsconfig.json: JSONDecodeError"]


def test_comment_and_comma_marks_inside_a_string_are_text(tmp_path):
    path = write(tmp_path, "tsconfig.json",
                 '{"a": "http://x/*y*/", "b": [1, 2,], "c": "q\\"//", "d": "x,]"}')
    assert read_config(path) == {"a": "http://x/*y*/", "b": [1, 2], "c": 'q"//', "d": "x,]"}


@pytest.mark.parametrize("pattern, root, own", [
    ("@components/*", "@components/Button", True),
    ("@components/*", "@comp/Button", False),
    ("utils/*", "utils", True),  # `utils/date` is read to its root, `utils`
    ("ut*", "utils", True),
    ("@lib", "@lib", True),
    ("lib", "lib2", False),
    ("*", "react", False),  # tsc's fallback for every name
])
def test_a_pattern_names_the_roots_tsc_would_send_to_the_project(pattern, root, own):
    assert names_own_files(pattern, root) is own
