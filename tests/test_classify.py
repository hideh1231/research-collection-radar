from radar.classify import classify
from radar.config import load_domains, repo_root
from radar.models import RawRecord


def test_source_rule_and_hri_keyword() -> None:
    cfg = load_domains(repo_root())
    raw = RawRecord(
        title="Adaptive Human-Robot Collaboration",
        url="https://example.org/x",
        source_url="https://example.org/",
        publisher="Frontiers",
        journal="Frontiers in Robotics and AI",
        collection_type="research_topic",
        discovered_via="frontiers-robotics",
    )
    domains, scores, _topics, method = classify(raw, cfg, "frontiers-robotics")
    assert "robotics" in domains
    assert "hri" in domains
    assert scores["robotics"] >= 0.65
    assert "source_rule" in method
