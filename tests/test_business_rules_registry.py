"""FR-09: the business rules, the code that reads them, docs/business-rules.md
and the per-rule behaviour tests stay in step. Fails when:
  - a seeded rule is missing from the doc (or the doc lists an unknown one);
  - code reads a rule key that was never seeded (admins can't change it —
    how the duplicate-invoice rules went unnoticed);
  - an enforced rule has no behaviour test, or a "not enforced" rule is read.
"""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(os.path.join(ROOT, path)) as f:
        return f.read()


def seeded_keys():
    keys = set()
    for f in glob.glob(os.path.join(ROOT, "services/auth-service/migrations/versions/*.py")):
        src = open(f).read()
        keys |= set(re.findall(r'"rule_key":\s*"([^"]+)"', src))
        keys |= set(re.findall(r"VALUES \(gen_random_uuid\(\), \"?\s*'([a-z_]+\.[a-z_]+)'", src))
        keys |= set(re.findall(r"^\s*\"?'([a-z_]+\.[a-z_]+)', '", src, re.M))
        keys |= set(re.findall(r'^\s*\(\s*"([a-z_]+\.[a-z_]+)",', src, re.M))
    return keys


def code_keys():
    keys = {}
    for f in glob.glob(os.path.join(ROOT, "services/*/app/**/*.py"), recursive=True):
        for k in re.findall(r'get_rule\(\s*["\']([a-z_]+\.[a-z_]+)["\']', open(f).read()):
            keys.setdefault(k, f)
        for k in re.findall(r'_hours\(\s*"([a-z_]+\.[a-z_]+)"', open(f).read()):
            keys.setdefault(k, f)
    return keys


def doc_sections():
    doc = _read("docs/business-rules.md")
    main, _, rest = doc.partition("## Not enforced")
    row = re.compile(r"^\| `([a-z_]+\.[a-z_]+)` \|", re.M)
    return set(row.findall(main)), set(row.findall(rest))


def behaviour_tests():
    names = set()
    for f in glob.glob(os.path.join(ROOT, "services/*/tests/test_rules_wiring.py")):
        names |= set(re.findall(r"^def (test_[a-z0-9_]+)\(", open(f).read(), re.M))
    return names


def test_every_seeded_rule_is_documented():
    enforced, not_enforced = doc_sections()
    documented = enforced | not_enforced
    seeded = seeded_keys()
    assert len(seeded) >= 46, f"seed parser found only {len(seeded)} rules (46 on 16 Oct)"
    assert seeded - documented == set(), f"undocumented rules: {sorted(seeded - documented)}"
    assert documented - seeded == set(), f"documented but never seeded: {sorted(documented - seeded)}"


def test_code_only_reads_seeded_rules():
    unknown = {k: f for k, f in code_keys().items() if k not in seeded_keys()}
    assert not unknown, f"code reads rules nobody can change: {unknown}"


def test_every_enforced_rule_has_a_behaviour_test():
    enforced, _ = doc_sections()
    tests = behaviour_tests()
    missing = sorted(k for k in enforced if "test_" + k.replace(".", "_") not in tests)
    assert not missing, f"enforced rules without a test in test_rules_wiring.py: {missing}"


def test_enforced_means_read_and_not_enforced_means_unread():
    enforced, not_enforced = doc_sections()
    read = set(code_keys())
    assert enforced - read == set(), f"documented as enforced but no code reads them: {sorted(enforced - read)}"
    assert not_enforced & read == set(), f"documented as not enforced but code reads them: {sorted(not_enforced & read)}"
