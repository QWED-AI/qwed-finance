"""The GitHub Action's scan modes count only verified rows as passed (#101).

A row with a missing or misnamed column, an unparseable or blank value, or a
file with no rows used to be reported as "All calculations verified!" with
errors_count=0 and exit 0. Each is now a failed row.
"""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("action_entrypoint", ROOT / "action_entrypoint.py")
action = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(action)

# One correct row per mode (values computed by the guards themselves).
GOOD = {
    "scan-npv": {"cashflows": "-1000,300,400,400,300", "rate": "0.1", "llm_npv": "$108.74"},
    "scan-bonds": {"face_value": "1000", "coupon_rate": "0.05", "price": "950", "years": "10", "llm_ytm": "5.66%"},
    "scan-fx": {"spot_rate": "1.10", "domestic_rate": "0.05", "foreign_rate": "0.02", "days": "90", "llm_forward": "1.10821"},
    "scan-risk": {"portfolio_value": "1000000", "volatility": "0.02", "confidence": "0.95", "holding_days": "1", "llm_var": "$32,900"},
}
CLAIM = {"scan-npv": "llm_npv", "scan-bonds": "llm_ytm", "scan-fx": "llm_forward", "scan-risk": "llm_var"}
MODES = list(GOOD)


def write_csv(path: Path, rows: list, columns: list | None = None) -> Path:
    columns = columns or list(rows[0])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_scan(mode, data_file, monkeypatch, tmp_path, capsys, fail_on_error="true", sarif=False):
    """Run a scan mode; return (exit_code, outputs, stdout)."""
    out = tmp_path / "github_output.txt"
    out.write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("INPUT_DATA_FILE", str(data_file))
    monkeypatch.setenv("INPUT_FAIL_ON_ERROR", fail_on_error)
    monkeypatch.setenv("INPUT_OUTPUT_FORMAT", "sarif" if sarif else "text")
    code = 0
    try:
        action.action_scan_file(mode)
    except SystemExit as e:
        code = e.code
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return code, outputs, capsys.readouterr().out


# -- the control still passes -----------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_correct_rows_pass(mode, monkeypatch, tmp_path, capsys):
    data = write_csv(tmp_path / "good.csv", [GOOD[mode], GOOD[mode]])
    code, out, stdout = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 0
    assert out["errors_count"] == "0"
    assert out["verified_count"] == "2"
    assert "passing" in out["badge_url"]
    assert "All calculations verified!" in stdout


# -- a missing or misnamed required column: every row skipped and failed -------------


RENAMES = [
    lambda c: c.upper(),                     # LLM_NPV, the issue's reproduction
    lambda c: c.replace("_", " "),           # separator: space
    lambda c: c.replace("_", "-"),           # separator: hyphen
    lambda c: c.replace("_", ""),            # glued together
    lambda c: c + " ",                       # trailing whitespace
    lambda c: c + "s",                       # inflection
    lambda c: c.replace("l", "\u04cf", 1),   # Cyrillic palochka look-alike
    lambda c: c[:3] + "\u200b" + c[3:],      # zero-width space
]


@pytest.mark.parametrize("rename", RENAMES, ids=["upper", "space", "hyphen", "glued", "trailing-space", "plural", "cyrillic", "zero-width"])
@pytest.mark.parametrize("mode", MODES)
def test_a_misnamed_claim_column_fails_every_row(mode, rename, monkeypatch, tmp_path, capsys):
    claim = CLAIM[mode]
    row = {(rename(k) if k == claim else k): v for k, v in GOOD[mode].items()}
    data = write_csv(tmp_path / "renamed.csv", [row, row])
    code, out, stdout = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "2"
    assert out["verified_count"] == "0"
    assert "failing" in out["badge_url"]
    assert "All calculations verified!" not in stdout
    assert "Missing required column" in stdout


# -- unparseable, blank or hostile claim values: the row fails ------------------------


BAD_CLAIMS = ["$999 thousand", "NaN", "", "   ", "\t", "abc", "5\n::warning::injected", "1e999999"]


@pytest.mark.parametrize("claim", BAD_CLAIMS, ids=["words", "nan", "empty", "spaces", "tab", "text", "workflow-command", "huge"])
@pytest.mark.parametrize("mode", MODES)
def test_an_unverifiable_claim_fails_the_row(mode, claim, monkeypatch, tmp_path, capsys):
    row = dict(GOOD[mode], **{CLAIM[mode]: claim})
    data = write_csv(tmp_path / "bad.csv", [row])
    code, out, stdout = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"
    # Nothing from the file reaches the log as a workflow command.
    assert not any(line.startswith("::") for line in stdout.splitlines())


@pytest.mark.parametrize("mode", MODES)
def test_a_blank_optional_cell_is_an_error_not_a_default(mode, monkeypatch, tmp_path, capsys):
    optional = next(c for c in action.SCAN_MODES[mode]["optional"])
    row = dict(GOOD[mode], **{optional: ""})
    data = write_csv(tmp_path / "blank.csv", [row])
    code, out, _ = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "1"


def test_an_absent_optional_column_uses_its_default_and_says_so(monkeypatch, tmp_path, capsys):
    """rate is absent from the whole file: its documented default 0.1 is used,
    which is the rate the control row assumes, and the log names it."""
    row = {k: v for k, v in GOOD["scan-npv"].items() if k != "rate"}
    data = write_csv(tmp_path / "norate.csv", [row])
    code, out, stdout = run_scan("scan-npv", data, monkeypatch, tmp_path, capsys)
    assert code == 0
    assert out["verified_count"] == "1"
    assert "Column 'rate' not in file; default 0.1 used" in stdout


# -- empty files, mixed files, fail_on_error=false, JSON, SARIF -----------------------


@pytest.mark.parametrize("mode", MODES)
def test_an_empty_file_fails(mode, monkeypatch, tmp_path, capsys):
    data = tmp_path / "empty.csv"
    data.write_text(",".join(GOOD[mode]) + "\n")
    code, out, stdout = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"
    assert "No rows were verified" in stdout


def test_one_good_and_one_bad_row_fails(monkeypatch, tmp_path, capsys):
    bad = dict(GOOD["scan-risk"], llm_var="NaN")
    data = write_csv(tmp_path / "mixed.csv", [GOOD["scan-risk"], bad])
    code, out, _ = run_scan("scan-risk", data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["verified_count"] == "1"
    assert out["errors_count"] == "1"


def test_fail_on_error_false_still_reports_the_failure(monkeypatch, tmp_path, capsys):
    row = {"cashflows": "-1000,300,400,400,300", "rate": "0.1", "LLM_NPV": "$108.74"}
    data = write_csv(tmp_path / "renamed.csv", [row])
    code, out, _ = run_scan("scan-npv", data, monkeypatch, tmp_path, capsys, fail_on_error="false")
    assert code == 0
    assert out["errors_count"] == "1"
    assert "failing" in out["badge_url"]


def test_a_json_record_missing_a_key_fails_that_row(monkeypatch, tmp_path, capsys):
    good = {k: float(v) if k != "llm_var" else v for k, v in GOOD["scan-risk"].items()}
    partial = {k: v for k, v in good.items() if k != "llm_var"}
    data = tmp_path / "rows.json"
    data.write_text(json.dumps([good, partial]))
    code, out, _ = run_scan("scan-risk", data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["verified_count"] == "1"
    assert out["errors_count"] == "1"


def test_sarif_reports_skipped_and_errored_rows(monkeypatch, tmp_path, capsys):
    bad = dict(GOOD["scan-npv"], llm_npv="abc")
    wrong = dict(GOOD["scan-npv"], llm_npv="$1.00")
    data = write_csv(tmp_path / "rows.csv", [GOOD["scan-npv"], bad, wrong])
    code, out, _ = run_scan("scan-npv", data, monkeypatch, tmp_path, capsys, sarif=True)
    assert code == 1
    sarif = json.loads((tmp_path / out["sarif_file"]).read_text())
    results = sarif["runs"][0]["results"]
    assert sorted((r["ruleId"], r["locations"][0]["physicalLocation"]["region"]["startLine"]) for r in results) == [
        ("QWED-FIN-001", 4),
        ("QWED-FIN-002", 3),
    ]
    rules = {r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    assert rules == {"QWED-FIN-001", "QWED-FIN-002"}
