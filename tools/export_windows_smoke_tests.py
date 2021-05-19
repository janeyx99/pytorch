#!/usr/bin/env python3

# import argparse
# import json
# import os
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from tools.stats_utils.s3_stat_parser import get_test_stats_summaries_for_job, Report, Version2Report, Status
from typing import cast, DefaultDict, Dict, List, Tuple

SMOKE_TESTS_FILE = '.pytorch-windows-smoke-tests'
SMOKE_TEST_CASE_THRESHOLD = 60.0

windows_gpu_ci_job_prefix = 'pytorch_windows_vs2019_py36_cuda'
linux_gpu_ci_job_prefix = 'pytorch_linux_xenial_cuda'

status_priority: Dict[Status, int] = {
    'failed': 1,
    'errored': 2,
    'skipped': 3,
    None: 4,
}

# We look for commits before yesterday to avoiding pulling incomplete reports
yesterday = str(datetime.now() - timedelta(days=1)).split(' ')[0]
branch = 'upstream/master'
# something like git rev-list --before="2021-05-18" --max-count=10 --remotes="*origin/master"
commits = subprocess.check_output(
    ["git", "rev-list", f"--before={yesterday}", "--max-count=50", f"--remotes=*{branch}"],
    encoding="ascii").splitlines()

test_names_to_times: DefaultDict[str, List[float]] = defaultdict(list)

# [blah_test_case: (failed_count, total_count)...]
windows_smoke_test_counts: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))

# we consider a test a potential smoke test if its status is "failed" compared to the base test status
def consider_smoke(test_case_name: str, test_status: Status, base_tests_statuses: Dict[str, Status]) -> bool:
    # If the test was not run in the base tests, we consider it as a smoke test
    if test_case_name not in base_tests_statuses or base_tests_statuses[test_case_name] == 'skipped':
        return True
    if test_status == 'failed' or test_status == 'errored':
        print(f'{test_case_name} on windows was {test_status} and on linux was {base_tests_statuses[test_case_name]}')
    return test_status == 'failed' or test_status == 'errored' and base_tests_statuses[test_case_name] is None


for commit in commits:
    print(commit)
    windows_reports: List[Report] = [
        report for l in get_test_stats_summaries_for_job(sha=commit, job_prefix=windows_gpu_ci_job_prefix).values() for report in l
    ]

    windows_test_names_to_status: Dict[str, Status] = dict()
    for report in windows_reports:
        if report.get('format_version', 1) != 2:
            raise RuntimeError("S3 format currently handled is version 2 only")
        v2report = cast(Version2Report, report)
        for test_file in v2report['files'].values():
            for suitename, test_suite in test_file['suites'].items():
                for casename, test_case in test_suite['cases'].items():
                    # The below attaches a __main__ as that matches the format of test.__class__ in
                    # common_utils.py (where this data will be used), and also matches what the output
                    # of a running test would look like.
                    name = f'{casename} (__main__.{suitename})'
                    succeeded: bool = test_case['status'] is None
                    if succeeded:
                        test_names_to_times[name].append(test_case['seconds'])

                    status: Status = test_case['status']
                    if name in windows_test_names_to_status:
                        old_status = windows_test_names_to_status[name]
                        if status_priority[status] < status_priority[old_status]:
                            windows_test_names_to_status[name] = status
                    windows_test_names_to_status[name] = status

    linux_reports = [report for l in get_test_stats_summaries_for_job(sha=commit, job_prefix=linux_gpu_ci_job_prefix).values() for report in l]
    linux_test_names_to_status: Dict[str, Status] = dict()
    for report in linux_reports:
        if report.get('format_version', 1) != 2:
            raise RuntimeError("S3 format currently handled is version 2 only")
        v2report = cast(Version2Report, report)
        for test_file in v2report['files'].values():
            for suitename, test_suite in test_file['suites'].items():
                for casename, test_case in test_suite['cases'].items():
                    # The below attaches a __main__ as that matches the format of test.__class__ in
                    # common_utils.py (where this data will be used), and also matches what the output
                    # of a running test would look like.
                    name = f'{casename} (__main__.{suitename})'
                    succeeded: bool = test_case['status'] is None
                    if succeeded:
                        test_names_to_times[name].append(test_case['seconds'])

                    status: Status = test_case['status']
                    if name in linux_test_names_to_status:
                        old_status = linux_test_names_to_status[name]
                        if status_priority[status] < status_priority[old_status]:
                            linux_test_names_to_status[name] = status
                    linux_test_names_to_status[name] = status

    for test_case, test_status in windows_test_names_to_status.items():
        failed_count, total_count = windows_smoke_test_counts[test_case]
        if consider_smoke(test_case, test_status, linux_test_names_to_status):
            windows_smoke_test_counts[test_case] = (failed_count + 1, total_count + 1)
        else:
            windows_smoke_test_counts[test_case] = (failed_count, total_count + 1)

test_case_times: Dict[str, float] = {test_case: statistics.mean(times) for test_case, times in test_names_to_times.items()}
filtered_windows_smoke_test_counts = {k: (x,y) for k, (x,y) in windows_smoke_test_counts.items() if x > 0}
print(filtered_windows_smoke_test_counts)

'''
def get_test_case_times() -> Dict[str, float]:
    windows_reports: List[Report] = get_previous_reports_for_branch('origin/viable/strict', windows_gpu_ci_job_prefix)
    # an entry will be like ("test_doc_examples (__main__.TestTypeHints)" -> [values]))
    test_names_to_times: DefaultDict[str, List[float]] = defaultdict(list)
    for report in windows_reports:
        if report.get('format_version', 1) != 2:
            raise RuntimeError("S3 format currently handled is version 2 only")
        v2report = cast(Version2Report, report)
        for test_file in v2report['files'].values():
            for suitename, test_suite in test_file['suites'].items():
                for casename, test_case in test_suite['cases'].items():
                    # The below attaches a __main__ as that matches the format of test.__class__ in
                    # common_utils.py (where this data will be used), and also matches what the output
                    # of a running test would look like.
                    name = f'{casename} (__main__.{suitename})'
                    succeeded: bool = test_case['status'] is None
                    if succeeded:
                        test_names_to_times[name].append(test_case['seconds'])
    return {test_case: statistics.mean(times) for test_case, times in test_names_to_times.items()}


def filter_slow_tests(test_cases_dict: Dict[str, float]) -> Dict[str, float]:
    return {test_case: time for test_case, time in test_cases_dict.items() if time >= SLOW_TEST_CASE_THRESHOLD_SEC}


def export_slow_tests(filename: str) -> None:
    if os.path.exists(filename):
        print(f'Overwriting existent file: {filename}')
    with open(filename, 'w+') as file:
        slow_test_times: Dict[str, float] = filter_slow_tests(get_test_case_times())
        json.dump(slow_test_times, file, indent='    ', separators=(',', ': '), sort_keys=True)
        file.write('\n')


def parse_args():
    parser = argparse.ArgumentParser(
        description='Export a JSON of slow test cases in PyTorch unit test suite')
    parser.add_argument(
        '-f',
        '--filename',
        nargs='?',
        type=str,
        default=SMOKE_TESTS_FILE,
        const=SMOKE_TESTS_FILE,
        help='Specify a file path to dump slow test times from previous S3 stats. Default file path: .pytorch-windows-smoke-tests',
    )
    return parser.parse_args()


def main():
    options = parse_args()
    export_slow_tests(options.filename)


if __name__ == '__main__':
    main()
'''
