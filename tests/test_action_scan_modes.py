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
_spec = importlib.util.spec_from_file_location(
    "action_entrypoint", ROOT / "action_entrypoint.py"
)
action = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(action)

# One correct row per mode (values computed by the guards themselves).
GOOD = {
    "scan-npv": {
        "cashflows": "-1000,300,400,400,300",
        "rate": "0.1",
        "llm_npv": "$108.74",
    },
    "scan-bonds": {
        "face_value": "1000",
        "coupon_rate": "0.05",
        "price": "950",
        "years": "10",
        "llm_ytm": "5.66%",
    },
    "scan-fx": {
        "spot_rate": "1.10",
        "domestic_rate": "0.05",
        "foreign_rate": "0.02",
        "days": "90",
        "llm_forward": "1.10821",
    },
    "scan-risk": {
        "portfolio_value": "1000000",
        "volatility": "0.02",
        "confidence": "0.95",
        "holding_days": "1",
        "llm_var": "$32,900",
    },
}
CLAIM = {
    "scan-npv": "llm_npv",
    "scan-bonds": "llm_ytm",
    "scan-fx": "llm_forward",
    "scan-risk": "llm_var",
}
MODES = list(GOOD)


def write_csv(path: Path, rows: list, columns: list | None = None) -> Path:
    columns = columns or list(rows[0])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_scan(
    mode, data_file, monkeypatch, tmp_path, capsys, fail_on_error="true", sarif=False
):
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
    outputs = dict(
        line.split("=", 1) for line in out.read_text().splitlines() if "=" in line
    )
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
    lambda c: c.upper(),  # LLM_NPV, the issue's reproduction
    lambda c: c.replace("_", " "),  # separator: space
    lambda c: c.replace("_", "-"),  # separator: hyphen
    lambda c: c.replace("_", ""),  # glued together
    lambda c: c + " ",  # trailing whitespace
    lambda c: c + "s",  # inflection
    lambda c: c.replace("l", "\u04cf", 1),  # Cyrillic palochka look-alike
    lambda c: c[:3] + "\u200b" + c[3:],  # zero-width space
]


@pytest.mark.parametrize(
    "rename",
    RENAMES,
    ids=[
        "upper",
        "space",
        "hyphen",
        "glued",
        "trailing-space",
        "plural",
        "cyrillic",
        "zero-width",
    ],
)
@pytest.mark.parametrize("mode", MODES)
def test_a_misnamed_claim_column_fails_every_row(
    mode, rename, monkeypatch, tmp_path, capsys
):
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


BAD_CLAIMS = [
    "$999 thousand",
    "NaN",
    "",
    "   ",
    "\t",
    "abc",
    "5\n::warning::injected",
    "1e999999",
]


@pytest.mark.parametrize(
    "claim",
    BAD_CLAIMS,
    ids=["words", "nan", "empty", "spaces", "tab", "text", "workflow-command", "huge"],
)
@pytest.mark.parametrize("mode", MODES)
def test_an_unverifiable_claim_fails_the_row(
    mode, claim, monkeypatch, tmp_path, capsys
):
    row = dict(GOOD[mode], **{CLAIM[mode]: claim})
    data = write_csv(tmp_path / "bad.csv", [row])
    code, out, stdout = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"
    # Nothing from the file reaches the log as a workflow command.
    assert not any(line.startswith("::") for line in stdout.splitlines())


@pytest.mark.parametrize("mode", MODES)
def test_a_blank_optional_cell_is_an_error_not_a_default(
    mode, monkeypatch, tmp_path, capsys
):
    optional = next(c for c in action.SCAN_MODES[mode]["optional"])
    row = dict(GOOD[mode], **{optional: ""})
    data = write_csv(tmp_path / "blank.csv", [row])
    code, out, _ = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "1"


def test_an_absent_optional_column_uses_its_default_and_says_so(
    monkeypatch, tmp_path, capsys
):
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
    code, out, _ = run_scan(
        "scan-npv", data, monkeypatch, tmp_path, capsys, fail_on_error="false"
    )
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
    assert sorted(
        (r["ruleId"], r["locations"][0]["physicalLocation"]["region"]["startLine"])
        for r in results
    ) == [
        ("QWED-FIN-001", 4),
        ("QWED-FIN-002", 3),
    ]
    rules = {r["id"] for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    assert rules == {"QWED-FIN-001", "QWED-FIN-002"}


# -- review round 1 ------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode, column, value",
    [
        ("scan-risk", "holding_days", "1.9"),
        ("scan-risk", "holding_days", "0.5"),
        ("scan-fx", "days", "90.5"),
        ("scan-npv", "rate", "Infinity"),
        ("scan-npv", "rate", "-inf"),
        ("scan-npv", "cashflows", "-100,inf"),
        ("scan-bonds", "price", "inf"),
        ("scan-fx", "spot_rate", "Infinity"),
        ("scan-risk", "portfolio_value", "inf"),
    ],
)
def test_non_finite_or_fractional_counts_fail_the_row(
    mode, column, value, monkeypatch, tmp_path, capsys
):
    """int() truncated 1.9 holding days to 1, and an infinite NPV rate left
    only the first cash flow: both verified a claim for different inputs."""
    row = dict(GOOD[mode], **{column: value})
    data = write_csv(tmp_path / "bad.csv", [row])
    code, out, _ = run_scan(mode, data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"


def test_a_whole_day_count_written_as_a_float_still_verifies(
    monkeypatch, tmp_path, capsys
):
    row = dict(GOOD["scan-risk"], holding_days="1.0")
    data = write_csv(tmp_path / "ok.csv", [row])
    code, out, _ = run_scan("scan-risk", data, monkeypatch, tmp_path, capsys)
    assert code == 0
    assert out["verified_count"] == "1"


@pytest.mark.parametrize("mode", ["scan-bonds", "scan-risk"])
def test_a_guard_refusal_is_an_error_not_a_mismatch(
    mode, monkeypatch, tmp_path, capsys
):
    """BondGuard and RiskGuard return UNVERIFIABLE for an unreadable claim
    instead of raising; nothing was compared, so it is QWED-FIN-002."""
    row = dict(GOOD[mode], **{CLAIM[mode]: "abc"})
    data = write_csv(tmp_path / "refused.csv", [row])
    code, out, stdout = run_scan(mode, data, monkeypatch, tmp_path, capsys, sarif=True)
    assert code == 1
    assert "(0 mismatch, 0 skipped, 1 error)" in stdout
    sarif = json.loads((tmp_path / out["sarif_file"]).read_text())
    assert [r["ruleId"] for r in sarif["runs"][0]["results"]] == ["QWED-FIN-002"]


def _sarif_lines(out, tmp_path):
    sarif = json.loads((tmp_path / out["sarif_file"]).read_text())
    return [
        r["locations"][0]["physicalLocation"]["region"]["startLine"]
        for r in sarif["runs"][0]["results"]
    ]


def test_sarif_lines_survive_blank_lines_and_multiline_values(
    monkeypatch, tmp_path, capsys
):
    data = tmp_path / "rows.csv"
    good = GOOD["scan-npv"]
    data.write_text(
        "cashflows,rate,llm_npv\n"
        f'"{good["cashflows"]}",0.1,"5\n::warning::x"\n'  # record on lines 2-3
        "\n"  # blank line 4, skipped
        f'"{good["cashflows"]}",0.1,abc\n',  # record on line 5
        encoding="utf-8",
    )
    code, out, _ = run_scan("scan-npv", data, monkeypatch, tmp_path, capsys, sarif=True)
    assert code == 1
    assert _sarif_lines(out, tmp_path) == [2, 5]


def test_json_findings_point_at_line_one(monkeypatch, tmp_path, capsys):
    """A compact JSON array is one line; record positions are not lines."""
    good = {
        "cashflows": GOOD["scan-npv"]["cashflows"],
        "rate": 0.1,
        "llm_npv": "$108.74",
    }
    data = tmp_path / "rows.json"
    data.write_text(json.dumps([good, dict(good, llm_npv="abc")]))
    code, out, _ = run_scan("scan-npv", data, monkeypatch, tmp_path, capsys, sarif=True)
    assert code == 1
    assert _sarif_lines(out, tmp_path) == [1]


def test_json_rows_labelled_by_string_do_not_crash(monkeypatch, tmp_path, capsys):
    """A column-oriented JSON export keeps trade ids as the index; adding a
    line offset to "trade-1" raised TypeError before any output was set."""
    data = tmp_path / "rows.json"
    data.write_text(
        json.dumps(
            {
                "cashflows": {"trade-1": GOOD["scan-npv"]["cashflows"]},
                "rate": {"trade-1": 0.1},
                "llm_npv": {"trade-1": "abc"},
            }
        )
    )
    code, out, _ = run_scan(
        "scan-npv", data, monkeypatch, tmp_path, capsys, fail_on_error="false"
    )
    assert code == 0
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"


@pytest.mark.parametrize(
    "content", ["", "  \n\n"], ids=["zero-byte", "whitespace-only"]
)
@pytest.mark.parametrize("fail_on_error, exit_code", [("true", 1), ("false", 0)])
def test_a_file_without_a_header_is_an_empty_scan(
    content, fail_on_error, exit_code, monkeypatch, tmp_path, capsys
):
    """pd.read_csv raised EmptyDataError before any output was set."""
    data = tmp_path / "empty.csv"
    data.write_text(content)
    code, out, stdout = run_scan(
        "scan-npv", data, monkeypatch, tmp_path, capsys, fail_on_error=fail_on_error
    )
    assert code == exit_code
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"
    assert "failing" in out["badge_url"]
    assert "No rows were verified" in stdout


# -- review round 2 ------------------------------------------------------------------


def test_a_whitespace_only_line_does_not_shift_sarif_lines(
    monkeypatch, tmp_path, capsys
):
    """pandas skips a whitespace-only line; the line map must skip it too."""
    good = GOOD["scan-npv"]["cashflows"]
    data = tmp_path / "rows.csv"
    data.write_text(
        f'cashflows,rate,llm_npv\n"{good}",0.1,$108.74\n   \n"{good}",0.1,abc\n'
    )
    code, out, _ = run_scan("scan-npv", data, monkeypatch, tmp_path, capsys, sarif=True)
    assert code == 1
    assert _sarif_lines(out, tmp_path) == [4]


@pytest.mark.parametrize("sarif", [True, False], ids=["sarif", "text"])
def test_a_field_past_the_csv_module_limit_does_not_abort(
    sarif, monkeypatch, tmp_path, capsys
):
    """pandas reads a 160,000-character field the csv module refuses: the scan
    still verifies, and SARIF findings fall back to line 1."""
    long_cashflows = "-1000," + ",".join(["100"] * 40000)
    data = write_csv(
        tmp_path / "long.csv",
        [{"cashflows": long_cashflows, "rate": "0.1", "llm_npv": "abc"}],
    )
    code, out, _ = run_scan(
        "scan-npv",
        data,
        monkeypatch,
        tmp_path,
        capsys,
        fail_on_error="false",
        sarif=sarif,
    )
    assert code == 0
    assert out["errors_count"] == "1"
    if sarif:
        assert _sarif_lines(out, tmp_path) == [1]


@pytest.mark.parametrize(
    "fmt, holding_days",
    [
        ("csv", "0.99999999999999999"),
        ("json-string", "0.99999999999999999"),
        ("json-number", 0.99999999999999999),
    ],
)
def test_a_day_count_just_under_one_is_not_rounded_to_whole(
    fmt, holding_days, monkeypatch, tmp_path, capsys
):
    """In float 0.99999999999999999 is 1.0: the file is read as exact text or
    Decimal, so the count is refused, not verified as one day."""
    if fmt == "csv":
        data = write_csv(
            tmp_path / "rows.csv", [dict(GOOD["scan-risk"], holding_days=holding_days)]
        )
    else:
        row = dict(GOOD["scan-risk"], holding_days="__DAYS__")
        text = json.dumps([row]).replace(
            '"__DAYS__"',
            json.dumps(holding_days) if fmt == "json-string" else "0.99999999999999999",
        )
        data = tmp_path / "rows.json"
        data.write_text(text)
    code, out, _ = run_scan("scan-risk", data, monkeypatch, tmp_path, capsys)
    assert code == 1
    assert out["verified_count"] == "0"


@pytest.mark.parametrize(
    "content",
    ["", "   \n", "{not json", '{"a": 1}'],
    ids=["zero-byte", "whitespace", "malformed", "scalars"],
)
def test_an_unreadable_json_file_is_a_failed_scan_with_outputs(
    content, monkeypatch, tmp_path, capsys
):
    data = tmp_path / "rows.json"
    data.write_text(content)
    code, out, _ = run_scan(
        "scan-npv", data, monkeypatch, tmp_path, capsys, fail_on_error="false"
    )
    assert code == 0
    assert out["errors_count"] == "1"
    assert out["verified_count"] == "0"
    assert "failing" in out["badge_url"]
