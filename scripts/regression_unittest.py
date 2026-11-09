"""Run unittest discovery and report actual record-store outcomes from that run."""

import argparse
import os
import sys
import unittest


class RegressionResult(unittest.TextTestResult):
    record_started = 0
    record_passed = 0

    def startTest(self, test):
        super().startTest(test)
        if type(test).__module__ == "test_formowl_records_store":
            self.record_started += 1

    def addSuccess(self, test):
        super().addSuccess(test)
        if type(test).__module__ == "test_formowl_records_store":
            self.record_passed += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-only", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("FORMOWL_RECORDS_TEST_DSN"):
        parser.error("run scripts/run_regression.sh to start a disposable pgvector database")
    pattern = "test_formowl_records_store.py" if args.records_only else "test*.py"
    suite = unittest.defaultTestLoader.discover("tests", pattern=pattern)
    result = unittest.TextTestRunner(resultclass=RegressionResult).run(suite)
    print(f"Record-store tests passed: {result.record_passed}/{result.record_started}", flush=True)
    return result.wasSuccessful() and 0 < result.record_started == result.record_passed


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
