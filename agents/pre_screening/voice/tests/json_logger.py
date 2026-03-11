"""
JSON-based test result logger.
Records every test outcome and writes a summary on teardown.
"""
import json
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class TestResultLog:
    test_name: str
    test_category: str
    passed: bool
    duration_seconds: float
    error_message: str = ""
    timestamp: str = ""


class TestRunLogger:
    """Collects results across an entire pytest session and writes to JSON."""

    def __init__(self):
        self.results: list[TestResultLog] = []
        self._start_times: dict[str, float] = {}

    def start_test(self, test_name: str):
        self._start_times[test_name] = time.time()

    def end_test(self, test_name: str, category: str, passed: bool, error_message: str = ""):
        duration = time.time() - self._start_times.pop(test_name, time.time())
        self.results.append(TestResultLog(
            test_name=test_name,
            test_category=category,
            passed=passed,
            duration_seconds=round(duration, 2),
            error_message=error_message,
            timestamp=datetime.now().isoformat(),
        ))

    def write(self, output_dir: Path | None = None) -> Path:
        if output_dir is None:
            output_dir = Path("test_results")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = output_dir / f"test_run_{timestamp}.json"

        by_category: dict[str, dict[str, int]] = {}
        for r in self.results:
            cat = r.test_category
            if cat not in by_category:
                by_category[cat] = {"total": 0, "passed": 0, "failed": 0}
            by_category[cat]["total"] += 1
            if r.passed:
                by_category[cat]["passed"] += 1
            else:
                by_category[cat]["failed"] += 1

        summary = {
            "timestamp": timestamp,
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed),
            "by_category": by_category,
            "results": [asdict(r) for r in self.results],
        }

        filepath.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return filepath
