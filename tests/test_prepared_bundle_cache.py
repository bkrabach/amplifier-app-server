"""Tests for prepared bundle cache keying in SessionManager.

Regression test for: hooks-a2a-server not loading because _prepare_bundle
cached a different bundle under the same key ('config-override:1.0.0').
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_server.session_manager import SessionManager


@pytest.fixture
def session_manager(tmp_path):
    """Create a SessionManager with a temp data dir."""
    return SessionManager(data_dir=tmp_path)


class TestPreparedBundleCacheCollision:
    """Two sessions with different bundles must not share a prepared cache entry.

    Root cause: After compose(), both bundles get name='config-override' version='1.0.0'
    from the override bundle. The _prepare_bundle cache key was f"{bundle.name}:{bundle.version}"
    which caused cortex-core's prepared bundle to be reused for cortex-a2a, dropping
    hooks-a2a-server.
    """

    @pytest.mark.asyncio
    async def test_different_bundles_get_different_prepared_results(self, session_manager):
        """Two composed bundles with same name but different content must prepare separately."""
        # Create two mock bundles with identical name/version (simulating post-compose)
        # but different hooks (simulating cortex-core vs cortex-a2a)
        bundle_core = MagicMock()
        bundle_core.name = "config-override"
        bundle_core.version = "1.0.0"
        bundle_core.hooks = [{"module": "hooks-logging"}]

        bundle_a2a = MagicMock()
        bundle_a2a.name = "config-override"
        bundle_a2a.version = "1.0.0"
        bundle_a2a.hooks = [{"module": "hooks-logging"}, {"module": "hooks-a2a-server"}]

        # Each bundle.prepare() should return a distinct prepared bundle
        prepared_core = MagicMock(name="prepared-core")
        prepared_core.hooks = bundle_core.hooks
        bundle_core.prepare = AsyncMock(return_value=prepared_core)

        prepared_a2a = MagicMock(name="prepared-a2a")
        prepared_a2a.hooks = bundle_a2a.hooks
        bundle_a2a.prepare = AsyncMock(return_value=prepared_a2a)

        # Prepare both bundles through the session manager
        result_core = await session_manager._prepare_bundle(
            bundle_core, bundle_uri="bundles/cortex-core.md"
        )
        result_a2a = await session_manager._prepare_bundle(
            bundle_a2a, bundle_uri="bundles/cortex-a2a.md"
        )

        # The critical assertion: they must NOT be the same object
        assert result_core is not result_a2a, (
            "Prepared bundle cache collision: cortex-a2a got cortex-core's prepared bundle. "
            "This causes hooks-a2a-server to not load."
        )

        # Both prepare() calls should have been invoked
        bundle_core.prepare.assert_awaited_once()
        bundle_a2a.prepare.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_same_bundle_uri_uses_cache(self, session_manager):
        """Same bundle URI should reuse the cached prepared result."""
        bundle = MagicMock()
        bundle.name = "config-override"
        bundle.version = "1.0.0"

        prepared = MagicMock(name="prepared")
        bundle.prepare = AsyncMock(return_value=prepared)

        result1 = await session_manager._prepare_bundle(bundle, bundle_uri="bundles/cortex-a2a.md")
        result2 = await session_manager._prepare_bundle(bundle, bundle_uri="bundles/cortex-a2a.md")

        assert result1 is result2, "Same bundle URI should return cached result"
        # prepare() should only be called once
        bundle.prepare.assert_awaited_once()
