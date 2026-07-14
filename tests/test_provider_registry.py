"""Provider registry tests."""

import pytest

from app.main import provider_registry as runtime_provider_registry
from app.providers.mock import MockProvider
from app.providers.registry import DuplicateProviderError, ProviderNotFoundError, ProviderRegistry


def test_runtime_registry_does_not_expose_mock_provider():
    """The mock is a test fixture only and is never offered by the app runtime."""

    assert all(provider.slug != "mock" for provider in runtime_provider_registry.providers())


def test_registry_registers_lists_and_returns_provider_by_slug():
    registry = ProviderRegistry()
    low_priority = MockProvider(slug="low")
    high_priority = MockProvider(slug="high")

    registry.register(low_priority, priority=20)
    registry.register(high_priority, priority=10)

    assert registry.get("low") is low_priority
    assert [provider.slug for provider in registry.providers()] == ["high", "low"]
    assert [provider.slug for provider in registry.enabled_providers()] == ["high", "low"]


def test_registry_rejects_duplicate_slug():
    registry = ProviderRegistry()
    registry.register(MockProvider(slug="same"))

    with pytest.raises(DuplicateProviderError):
        registry.register(MockProvider(slug="same"))


def test_registry_rejects_unknown_provider():
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotFoundError):
        registry.get("missing")

    with pytest.raises(ProviderNotFoundError):
        registry.select(["missing"])


def test_registry_selects_one_or_many_enabled_providers_in_priority_order():
    registry = ProviderRegistry()
    registry.register(MockProvider(slug="disabled"), enabled=False, priority=1)
    registry.register(MockProvider(slug="second"), priority=20)
    registry.register(MockProvider(slug="first"), priority=10)

    assert [provider.slug for provider in registry.select(["second", "first"])] == ["first", "second"]
    assert [provider.slug for provider in registry.select()] == ["first", "second"]
    assert registry.select(["disabled"]) == []
