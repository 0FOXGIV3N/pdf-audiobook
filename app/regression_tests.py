import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_CASES_PATH = Path(__file__).with_name("regression_cases.json")


@dataclass
class RegressionResult:
    case_id: str
    description: str
    expected: str
    status: str
    file: str
    detail: str


def normalize_for_search(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_file(book_dir: Path, relative_path: str) -> Tuple[Optional[str], Optional[str]]:
    path = book_dir / relative_path
    if not path.exists():
        return None, f"missing file: {path}"
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as exc:
        return None, f"could not read {path}: {exc}"


def line_matches(text: str, pattern: str) -> bool:
    rx = re.compile(pattern)
    return any(rx.fullmatch(line.strip()) for line in text.splitlines())


def evaluate_case(book_dir: Path, case: Dict[str, Any]) -> RegressionResult:
    case_id = case.get("id", "untitled_case")
    description = case.get("description", "")
    expected = case.get("expected", "pass")
    relative_file = case.get("file", "")

    text, error = read_file(book_dir, relative_file)
    if error:
        actual_pass = False
        detail = error
    else:
        assert text is not None
        actual_pass = True
        details = []

        if "must_contain" in case:
            needle = normalize_for_search(str(case["must_contain"]))
            haystack = normalize_for_search(text)
            if needle not in haystack:
                actual_pass = False
                details.append(f"missing phrase: {case['must_contain']}")

        if "must_not_contain" in case:
            needle = normalize_for_search(str(case["must_not_contain"]))
            haystack = normalize_for_search(text)
            if needle in haystack:
                actual_pass = False
                details.append(f"forbidden phrase found: {case['must_not_contain']}")

        if "must_match_line" in case:
            pattern = str(case["must_match_line"])
            if not line_matches(text, pattern):
                actual_pass = False
                details.append(f"no line matched regex: {pattern}")

        if "must_not_match_line" in case:
            pattern = str(case["must_not_match_line"])
            if line_matches(text, pattern):
                actual_pass = False
                details.append(f"forbidden standalone line matched regex: {pattern}")

        detail = "; ".join(details) if details else "ok"

    if expected == "known_fail":
        if actual_pass:
            status = "RESOLVED"
            detail = "known failure now passes; consider changing expected to pass"
        else:
            status = "KNOWN_FAIL"
    else:
        status = "PASS" if actual_pass else "FAIL"

    return RegressionResult(
        case_id=case_id,
        description=description,
        expected=expected,
        status=status,
        file=relative_file,
        detail=detail,
    )


def load_cases(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Regression cases file must contain a JSON list.")
    return data


def build_text_report(results: List[RegressionResult], book_dir: Path, cases_path: Path) -> str:
    counts = {"PASS": 0, "FAIL": 0, "KNOWN_FAIL": 0, "RESOLVED": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    lines = []
    lines.append("PDF Audiobook Generator - Regression Report")
    lines.append("=" * 58)
    lines.append("")
    lines.append(f"Book output: {book_dir}")
    lines.append(f"Cases file:  {cases_path}")
    lines.append("")
    lines.append(f"PASS:        {counts.get('PASS', 0)}")
    lines.append(f"FAIL:        {counts.get('FAIL', 0)}")
    lines.append(f"KNOWN_FAIL:  {counts.get('KNOWN_FAIL', 0)}")
    lines.append(f"RESOLVED:    {counts.get('RESOLVED', 0)}")
    lines.append("")
    lines.append("Cases")
    lines.append("-" * 58)

    for result in results:
        lines.append(f"[{result.status}] {result.case_id}")
        lines.append(f"  {result.description}")
        lines.append(f"  file: {result.file}")
        lines.append(f"  detail: {result.detail}")
        lines.append("")

    lines.append("Notes")
    lines.append("-" * 58)
    lines.append("KNOWN_FAIL means the test captures a current bug without failing the suite.")
    lines.append("RESOLVED means a known failure now passes and should be promoted to expected pass.")
    lines.append("This test suite does not modify output files.")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PDF audiobook regression checks against generated output.")
    parser.add_argument("book_output_dir", help="Book output directory, e.g. /output/AI Revolution_DVG_2025")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to regression_cases.json")
    parser.add_argument("--strict-known-fail", action="store_true", help="Treat known failures as failures.")
    args = parser.parse_args()

    book_dir = Path(args.book_output_dir)
    cases_path = Path(args.cases)

    if not book_dir.exists():
        print(f"Book output directory not found: {book_dir}")
        return 2

    try:
        cases = load_cases(cases_path)
    except Exception as exc:
        print(f"Could not load cases: {exc}")
        return 2

    results = [evaluate_case(book_dir, case) for case in cases]

    report_text = build_text_report(results, book_dir, cases_path)
    report_path = book_dir / "regression_report.txt"
    report_json_path = book_dir / "regression_report.json"

    report_path.write_text(report_text, encoding="utf-8")
    report_json_path.write_text(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False), encoding="utf-8")

    print(report_text)
    print(f"Wrote: {report_path}")
    print(f"Wrote: {report_json_path}")

    has_fail = any(r.status == "FAIL" for r in results)
    has_known_fail = any(r.status == "KNOWN_FAIL" for r in results)

    if has_fail or (args.strict_known_fail and has_known_fail):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
