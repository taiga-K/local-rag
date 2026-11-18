"""Route registration order for the engineer aliases.

Principle: boundary. Starlette uses the first matching route.
PipesHub registers the fixed vector-store path so it is not a connector id.
No PipesHub test covers this alias. test_viewpoints.md has no route-order case.
"""

from kbindex.api import create_app


def test_vector_store_reindex_is_not_captured_by_connector_id():
    app = create_app()
    paths = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "POST" in methods and "/connectors/" in path and path.endswith("/reindex"):
            paths.append(path)
    fixed = "/api/v1/connectors/vector-store/reindex"
    wildcard = "/api/v1/connectors/{connector_id}/reindex"
    assert fixed in paths and wildcard in paths
    assert paths.index(fixed) < paths.index(wildcard)
