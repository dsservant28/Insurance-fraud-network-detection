"""Tests for scripts/policy_check.py.

These check two of the hardest requirements automatically:
  - labels are separate from features (detector never touches ground truth)
  - fixed-seed reproducibility (generator never uses unseeded randomness or the clock)
plus a basic "no secrets in the repo" rule.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("policy_check", ROOT / "scripts" / "policy_check.py")
policy_check = importlib.util.module_from_spec(_spec)
sys.modules["policy_check"] = policy_check  # needed so dataclasses can resolve the module
_spec.loader.exec_module(policy_check)


def _write(root: Path, rel: str, code: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def _rules(violations):
    return {v.rule for v in violations}


def test_real_project_has_no_violations():
    violations = policy_check.check_repo(ROOT)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_detector_reading_ground_truth_is_caught(tmp_path):
    f = _write(tmp_path, "src/fraudnet/detect/score.py", "labels = pd.read_csv('data/ground_truth.csv')\n")
    assert "R1-leakage" in _rules(policy_check.check_file(f, tmp_path))


def test_detector_using_label_column_is_caught(tmp_path):
    f = _write(tmp_path, "src/fraudnet/detect/features.py", "x = claims['is_fraud']\n")
    assert "R1-leakage" in _rules(policy_check.check_file(f, tmp_path))


def test_evaluation_may_read_ground_truth(tmp_path):
    f = _write(tmp_path, "src/fraudnet/evaluate/metrics.py", "truth = pd.read_csv('data/ground_truth.csv')\n")
    assert policy_check.check_file(f, tmp_path) == []


def test_generator_global_random_is_caught(tmp_path):
    for code in ("import random\n", "from random import choice\n",
                 "x = np.random.randint(0, 5)\n", "np.random.seed(1)\n"):
        f = _write(tmp_path, "src/fraudnet/generate/claims.py", code)
        assert "R2-determinism" in _rules(policy_check.check_file(f, tmp_path)), code


def test_generator_wall_clock_is_caught(tmp_path):
    f = _write(tmp_path, "src/fraudnet/generate/dates.py", "today = date.today()\n")
    assert "R2-determinism" in _rules(policy_check.check_file(f, tmp_path))


def test_generator_seeded_rng_is_allowed(tmp_path):
    code = "rng = np.random.default_rng(seed)\nn = rng.integers(0, 5)\n"
    f = _write(tmp_path, "src/fraudnet/generate/claims.py", code)
    assert policy_check.check_file(f, tmp_path) == []


def test_hard_coded_secret_is_caught(tmp_path):
    fake_key = "sk-" + "a1B2" * 6  # built at runtime so this test file itself holds no key
    f = _write(tmp_path, "src/fraudnet/app/config.py", f"KEY = '{fake_key}'\n")
    assert "R3-secret" in _rules(policy_check.check_file(f, tmp_path))


def test_db_url_with_password_is_caught(tmp_path):
    url = "postgresql://fraud:" + "pw123456" + "@localhost:5432/fraud"
    f = _write(tmp_path, "src/fraudnet/app/db.py", f"URL = '{url}'\n")
    assert "R3-secret" in _rules(policy_check.check_file(f, tmp_path))


def test_allow_marker_skips_line(tmp_path):
    f = _write(tmp_path, "src/fraudnet/detect/doc.py", "# never read ground_truth here  # policy: allow\n")
    assert policy_check.check_file(f, tmp_path) == []
