from radar.collectors.registry import REGISTRY
from radar.config import load_sources
from radar.ids import allowed_url


def test_source_keys_are_unique_and_collectors_exist() -> None:
    sources = load_sources()["sources"]
    keys = [source["key"] for source in sources]
    assert len(keys) == len(set(keys))
    assert all(source["collector"] in REGISTRY for source in sources)


def test_enabled_sources_have_allowed_hosts() -> None:
    enabled = [source for source in load_sources()["sources"] if source.get("enabled")]
    assert enabled
    assert all(source.get("allowed_hosts") for source in enabled)


def test_source_entry_urls_are_allowed_and_not_registered_twice() -> None:
    sources = load_sources()["sources"]
    identities = [(source["collector"], source["url"]) for source in sources]
    assert len(identities) == len(set(identities))
    assert all(allowed_url(source["url"], source["allowed_hosts"]) for source in sources)
