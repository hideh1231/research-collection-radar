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


def test_scientific_reports_is_not_forced_into_psychology() -> None:
    cfg = load_domains(repo_root())
    raw = RawRecord(
        title="Catalytic oxidation of methane",
        url="https://example.org/chem",
        source_url="https://www.nature.com/srep/calls-for-papers",
        publisher="Nature Portfolio",
        journal="Scientific Reports",
        collection_type="collection",
        discovered_via="nature-psychology",
    )
    domains, _scores, _topics, method = classify(raw, cfg, "nature-psychology")
    assert "psychology" not in domains
    assert "source_rule" not in method


def test_comms_psychology_and_neurorobotics_rules() -> None:
    cfg = load_domains(repo_root())
    comms = RawRecord(
        title="A methods collection",
        url="https://example.org/x",
        source_url="https://example.org/",
        publisher="Nature Portfolio",
        journal="Communications Psychology",
        collection_type="collection",
        discovered_via="nature-comms-psychology",
    )
    domains, _scores, _topics, method = classify(comms, cfg, "nature-comms-psychology")
    assert "psychology" in domains
    assert "source_rule" in method
    nature_neuro = RawRecord(
        title="A methods collection",
        url="https://nature.com/collections/abc",
        source_url="https://www.nature.com/neuro/collections",
        publisher="Nature Portfolio",
        journal="Nature Neuroscience",
        collection_type="collection",
        discovered_via="nature-neuro",
    )
    domains, _scores, _topics, method = classify(nature_neuro, cfg, "nature-neuro")
    assert "neuroscience" in domains
    assert "source_rule" in method
    neuro = RawRecord(
        title="Adaptive locomotion",
        url="https://example.org/y",
        source_url="https://example.org/",
        publisher="Frontiers",
        journal="Frontiers in Neurorobotics",
        collection_type="research_topic",
        discovered_via="frontiers-neurorobotics",
    )
    domains, _scores, _topics, method = classify(neuro, cfg, "frontiers-neurorobotics")
    assert "robotics" in domains
    assert "hri" in domains
