import configparser
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from enum import Enum

import click


class FileStatus(Enum):
    ADDED = 1
    MODIFIED = 2
    DELETED = 3
    RENAMED = 4
    OTHER = 5


def map_git_status(str_status):

    if str_status.startswith("A"):
        return FileStatus.ADDED
    elif str_status.startswith("M"):
        return FileStatus.MODIFIED
    elif str_status.startswith("D"):
        return FileStatus.DELETED
    elif str_status.startswith("R"):
        return FileStatus.RENAMED
    else:
        return FileStatus.OTHER


# special files/extensions that trigger full tests when modified (instead of partial tests)
SPECIAL_FILES_DEFAULT = [
    "setup.py",
    "setup.cfg",
    "setup_ts1.py",
    "setup_ts1.cfg",
    "setup_ts2.py",
    "setup_ts2.cfg",
    "Jenkinsfile",
]
SPECIAL_EXTENSIONS_DEFAULT = [
    ".pkl",
    ".h5",
    ".csv",
    ".gz",
    ".json",
    ".png",
    ".xml",
    ".p",
    ".groovy",
]
CODE_EXTENSIONS = [".py"]
NO_TESTS_EXTENSIONS = [".md", ".rst", ".tex", ".txt"]

TEST_FILES_TO_RUN_ALL_STAGES = "test_files_to_run.txt"
TEST_STAGES = ["unit", "integration", "integration_db"]
COVERAGE_FILE = ".coverage"
CONFIG_FILE = "~/.partialtesting"
DEFAULT_BRANCH_TO_COMPARE = "origin/master"


class File:
    """
    Represents a file and its status relevant to partialtesting:
    - path
    - is it a test file?
    - has it been moved/renamed?
    - git status: added (new), changed, etc.
    """

    def __init__(self, path, status, new_path=None):
        self.path = path
        self.new_path = new_path  # for renamed files
        self.status = map_git_status(status)

    def is_test_file(self):
        return self.path.startswith("tests/")

    def __repr__(self):
        return f"{{File {self.path}, {self.status}}}"


class Project:
    """
    Represents the project that is being partialtested.
    Given the name and the coverage_dir, find and hold
    the path to the .coverage file.
    - name: name of the project. It should match the
    directory containing coverage data
    - coverage_db_path: path to coverage data
    - line_coverage: tracks whether the .coverage file
    recorded line or --branch coverage
    """

    def __init__(self, name, coverage_dir, build_number="", line_coverage=False):

        self.name = name
        self.line_coverage = line_coverage

        build_path = f"{coverage_dir}/{self.name}/"

        if not build_number:
            build_number = get_last_build_directory(build_path)

        self.coverage_db_path = f"{build_path}{build_number}/{COVERAGE_FILE}"
        logging.info(f"Partial Testing: using coverage file '{self.coverage_db_path}'")


def run_sh_cmd(command_and_params):
    """
    run a shell command and return the std output
    """
    logging.info(f"Partial Testing: Running: {command_and_params}")
    result = subprocess.run(
        command_and_params, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")
    return stdout, stderr


def is_code_file(filepath):
    """
    Check if the file is considered a source-code file
    """
    for code_ext in CODE_EXTENSIONS:
        if filepath.endswith(code_ext):
            return True

    return False


def get_last_build_directory(path):
    """
    Given the path to a directory containing multiple build
    directories, get the latest one.
    """
    ls_out, ls_err = run_sh_cmd(["ls", "-t1", path])

    if ls_err and "No such file or directory" in ls_err:
        raise Exception(f"Could not find coverage data for the project under {path}")
    elif not ls_out and not ls_err:
        if os.path.isfile(f"{path}/{COVERAGE_FILE}"):
            return '.'  # this directory contains .coverage

    build_directory = ls_out.splitlines()[0]

    return build_directory


def connect_to_db(coverage_db_path):
    """
    Connect (load) the .coverage DB file which
    contains the saved coverage information
    from previous runs
    """
    db = sqlite3.connect(coverage_db_path)
    return db, db.cursor()


def get_tests_that_use_file(changed_file, coverage_db_path, line_coverage=False):
    """
    SQL query based on:
    https://nedbatchelder.com/blog/201810/who_tests_what_is_here.html
    https://nedbatchelder.com/blog/201612/who_tests_what.html
    DB Schema available at:
    https://github.com/nedbat/coveragepy/blob/master/doc/dbschema.rst

    The check to filter out empty contexts is based on:
    https://github.com/nedbat/coveragepy/issues/796
    """
    test_names = []

    cov_table = "arc" if not line_coverage else "line_bits"

    sql_query = f"""\
select distinct context.context from {cov_table}, file, context \
where {cov_table}.file_id = file.id and {cov_table}.context_id = context.id and \
file.path like ? and context.context != '' \
"""
    db, cursor = connect_to_db(coverage_db_path)

    cursor.execute(sql_query, (f"%{changed_file}", ))

    for row in cursor.fetchall():
        test_names.append(row[0])

    return test_names


def get_test_files_for_test_names(test_names, tests_dir="tests"):
    """
    Given a set of test names, find the test files in which they are defined
    """

    # rstrip to avoid grep adding two slashes
    # https://unix.stackexchange.com/questions/288757/why-does-grep-sometimes-return-directories-with-two-slashes
    tests_dir = tests_dir.rstrip("/")

    def _get_test_func_name(test_name):
        if "." in test_name:
            # fully qualified test name in the newest coverage (version >= v5.0a6)
            # https://github.com/nedbat/coveragepy/commit/a9f5f7fadacaa8a84b4ac247e79bcb6f29935bb1
            return test_name.rpartition(".")[2]
        return test_name

    # Write test function names to a file grep can use as patterns
    test_func_names = (_get_test_func_name(test_name) for test_name in test_names)
    with tempfile.NamedTemporaryFile(
        mode="wt", prefix="pt_grep_patterns", delete=False
    ) as grep_patterns_f:
        grep_patterns_f.writelines(
            f"{test_func_name}\n" for test_func_name in test_func_names
        )

    all_test_files_str, _ = run_sh_cmd(
        ["grep", "-Rlf", grep_patterns_f.name, "--include=test_*.py", tests_dir]
    )
    all_test_files = all_test_files_str.splitlines()

    logging.debug(f"Partial Testing: Tests found in files '{all_test_files_str}'")
    os.remove(grep_patterns_f.name)
    return all_test_files


def parse_git_diff_name_status(git_output):
    """
    Parse the output of 'git diff --name-status ...'
    and return File objects to represent it
    """
    logging.debug(f"Partial Testing: git diff: {git_output}")

    files = []
    for line in git_output.splitlines():
        """
        Most lines will have 2 parts: status + path
        Exception: renamed files produce lines with 3 parts: status + old_path + new_path
        When a rename occurs:
            - use the old file name to check against the saved coverage data
            - for test files: save the new name, as it needs to be passed to pytest
        """
        line_array = line.split()
        status, path = line_array[0], line_array[1]
        new_path = None

        if len(line_array) > 2:
            new_path = line_array[2]

        files.append(File(path, status, new_path))

    return files


def git_diff_namestatus(compare_to_branch=DEFAULT_BRANCH_TO_COMPARE):
    """
    Used when running partial_testing in jenkins.
    'git diff' is done using the changes that were committed to the branch
    """
    git_merge_out, _ = run_sh_cmd(["git", "merge-base", "HEAD", compare_to_branch])
    git_merge_base_commit = git_merge_out.splitlines()[0]
    git_diff_output, _ = run_sh_cmd(
        ["git", "diff", "--name-status", f"{git_merge_base_commit}..HEAD"]
    )
    return git_diff_output


def git_diff_uncommitted(compare_to_branch=DEFAULT_BRANCH_TO_COMPARE):
    """
    Used when running partial_testing locally.
    'git diff' is done using the uncommitted changes
    """
    git_diff_output, _ = run_sh_cmd(["git", "diff", "--name-status", compare_to_branch])
    return git_diff_output


def detect_changed_files(git_diff_use_head, compare_to_branch):

    if git_diff_use_head:
        git_diff_output = git_diff_namestatus(compare_to_branch)
    else:
        git_diff_output = git_diff_uncommitted(compare_to_branch)

    changed_files = parse_git_diff_name_status(git_diff_output)
    logging.info(f"Partial Testing: changed files {changed_files}")
    return changed_files


def new_nontest_code_file_added(nontest_files):
    """
    Checks wether a new code file (not readme.md for example),
    that is not a test file, was added
    """
    for nontest_file in nontest_files:
        if nontest_file.status == FileStatus.ADDED and is_code_file(nontest_file.path):
            logging.info(
                f"Partial Testing: a nontest file was added: {nontest_file.path}"
            )
            return True

    return False


def modified_special_file(nontest_files, special_files):
    """
    Check if any of the added/deleted/modified files is a special file
    """
    for file in nontest_files:
        if file.path in special_files:
            logging.info(f"Partial Testing: a special file was modified: {file.path}")
            return True

    return False


def modified_file_with_special_or_unknown_extension(modified_files, special_extensions):
    """
    Check if any of the added/deleted/modified is of an special_extension type
    """

    other_known_extensions = CODE_EXTENSIONS + NO_TESTS_EXTENSIONS

    for mod_file in modified_files:

        _, file_ext = os.path.splitext(mod_file.path)

        if file_ext in special_extensions:
            return True

        if file_ext not in other_known_extensions:
            return True

        if mod_file.path.endswith("conftest.py"):
            return True

    return False


def full_test_required(nontest_files, test_files, special_files, special_extensions):
    """
    Determine weather we need to run a full test or not.
    Read possible scenarios in http://docs/core/services/partial_testing/
    """

    if new_nontest_code_file_added(nontest_files):
        logging.info(
            "Partial Testing: New nontest files were added, a full test is required"
        )
        return True

    if modified_special_file(nontest_files + test_files, special_files):
        logging.info(
            "Partial Testing: a special file was modified, a full test is required"
        )
        return True

    if modified_file_with_special_or_unknown_extension(
        nontest_files + test_files, special_extensions
    ):
        logging.info(
            "Partial Testing: a file with a special/unknown extension was modified, a full test is required"
        )
        return True

    return False


def identify_tests_related_to_modified_files(modified_files, project_data):
    """
    Given a list of files that have been modified or deleted,
    check which tests use them and return the files they are in
    """

    all_test_names = []
    for file in modified_files:
        test_names = get_tests_that_use_file(file.path, project_data.coverage_db_path, project_data.line_coverage)
        logging.debug(f"Partial Testing: file '{file}' triggers test: '{test_names}'")
        all_test_names.extend(test_names)

    return all_test_names


def identify_files_to_test_for_modified_files(modified_files, project_data):
    """
    Given a list of files that have been modified or deleted,
    check which tests use them and return the files they are in
    """
    test_names = identify_tests_related_to_modified_files(modified_files, project_data)
    test_files = get_test_files_for_test_names(test_names)

    return test_files


def identify_files_to_test_for_testfiles(test_files):
    """
    Given a list of changed test files, return which files need to be tested.
    - Deleted test files should not be run.
    - Renamed test files should only run using the new name

    This function assumes that special file detection has already been done
    so it does not care about them
    """
    files_to_test = []
    for file in test_files:
        if file.status == FileStatus.DELETED:
            continue
        elif file.status == FileStatus.RENAMED:
            files_to_test.append(file.new_path)
        else:
            files_to_test.append(file.path)

    return files_to_test


def separate_test_files(diff_files):

    nontest_files = []
    test_files = []
    for file in diff_files:
        test_files.append(file) if file.is_test_file() else nontest_files.append(file)

    return nontest_files, test_files


def identify_files_to_test(nontest_files, test_files, project_data):
    """
    given a list of of files that have been added/deleted/modified
    identify what tests if any need to be run
    """

    # both nontest_files and test_files are used to find related test files
    # because a file under tests/ might be a utility file that is imported
    # in other test files
    files_to_test_1 = identify_files_to_test_for_modified_files(
        nontest_files + test_files, project_data
    )
    files_to_test_2 = identify_files_to_test_for_testfiles(test_files)

    return set(files_to_test_1 + files_to_test_2)


def write_file_of_test_files_to_run(test_files, output_file):

    # Write a file containing all tests files that need to be run
    test_files_printable = ""
    for test_file in test_files:
        test_files_printable += f"{test_file}\n"

    with open(output_file, "w") as all_tests_file:
        # create the file even if there are no files to test
        logging.info(f"Creating file {output_file}")
        all_tests_file.write(f"{test_files_printable}")

    logging.info(f"Partial Testing: relevant test files:\n{test_files_printable}")


def detect_relevant_tests(
    project_name,
    coverage_dir,
    git_diff_use_head,
    special_files=SPECIAL_FILES_DEFAULT,
    special_extensions=SPECIAL_EXTENSIONS_DEFAULT,
    output_file=TEST_FILES_TO_RUN_ALL_STAGES,
    compare_to_branch=DEFAULT_BRANCH_TO_COMPARE,
    line_coverage=False,
):
    """
    For a change set (defined by git diff), determine which tests need to be run.

    Possible return values:
    a) None  -> a full test is required
    b) set() -> no tests need to be run (empty set)
    c) {'tests/unit/test_file_1.py', 'tests/unit/test_file_2.py'}
        -> run tests within the mentioned files
    """

    try:
        project_data = Project(project_name, coverage_dir, line_coverage=line_coverage)
    except Exception as e:
        logging.error(
            f"Partial Testing: could not access the project's information. A full test will be done. Reason: {e}"
        )
        return None

    nontest_files, test_files = separate_test_files(
        detect_changed_files(git_diff_use_head, compare_to_branch)
    )

    if full_test_required(nontest_files, test_files, special_files, special_extensions):
        # a full test is needed, do not write partial testing instructions
        logging.info(f"Partial Testing: a full test is required")
        return None

    files_to_test = identify_files_to_test(nontest_files, test_files, project_data)
    write_file_of_test_files_to_run(files_to_test, output_file)

    return files_to_test


def str_to_list(strlist):
    """
    Given the string "[file1, file2]" from a Jenkins job (groovy) return the list ["file1", "file2"]
    """
    strlist = strlist.replace("]", "").replace("[", "").replace(" ", "")

    result = strlist.split(",")
    return result


@click.command()
@click.option(
    "--coverage-dir",
    help=f"Path to the saved coverage data.\n"
    "Set a default path by setting the below in ~/.partialtesting:\n"
    "[coverage]\ndir=<path>",
)
@click.option(
    "--project-name",
    required=True,
    help=f"Project name (e.g. numpy)."
    "The name will be used to get the path to the coverage data "
    "for this project:\n<coverage_dir>/<project_name>/.../.coverage\n",
)
@click.option(
    "--git-diff-use-head",
    is_flag=True,
    help=f"If running on jenkins "
    "compare git changes using HEAD, otherwise, for local usage, "
    "compare against uncommitted changes",
)
@click.option(
    "--special-files",
    default=SPECIAL_FILES_DEFAULT,
    help=f"Files that trigger a full test run. Default: {SPECIAL_FILES_DEFAULT}",
)
@click.option(
    "--special-extensions",
    default=SPECIAL_EXTENSIONS_DEFAULT,
    help=f"Extensions that trigger a full test run. Default: {SPECIAL_EXTENSIONS_DEFAULT}",
)
@click.option(
    "--output-file",
    default=TEST_FILES_TO_RUN_ALL_STAGES,
    help=f"Desired path/name for the output file that contains the tests "
    f"that need to be run (output). Default: {TEST_FILES_TO_RUN_ALL_STAGES}",
)
@click.option(
    "--compare-to-branch",
    default=DEFAULT_BRANCH_TO_COMPARE,
    help=f"Desired to compare changes against "
    f"when doing 'git diff'. Default: {DEFAULT_BRANCH_TO_COMPARE}",
)
@click.option(
    "--line-coverage",
    is_flag=True,
    help=f"If recording line coverage instead of "
    "branch coverage (coverage run --branch) ",
)
def main(
    project_name,
    coverage_dir,
    git_diff_use_head,
    special_files,
    special_extensions,
    output_file,
    compare_to_branch,
    line_coverage,
):
    """
    Partial Testing (PT) identifies which tests need to be run for a given
    change or pull-request, improving the speed of testing, developer
    productivity and resource usage. To achieve this, PT relies on enriched
    coverage data generated before hand, generally by a master-branch build
    running on a CI (e.g. Jenkins).

    PT expects to find the coverage data in a directory with the below pattern:
    <coverage_dir>/<project_name>.
    Use the options for this script to specify them

    More information available at
    github.com/man-group/partialtesting/blob/master/README.md
    """
    config = configparser.ConfigParser()
    config.read(os.path.expanduser(CONFIG_FILE))
    if not coverage_dir:
        try:
            coverage_dir = config["coverage"]["dir"]
        except KeyError:
            click.secho(
                "No coverage_directory provided.\n"
                "Please set it via --coverage-dir or ~/.partialtesting\n"
                "See --help for more information\n"
            )
            sys.exit(1)

    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    if isinstance(special_files, str):
        special_files = str_to_list(special_files)

    if isinstance(special_extensions, str):
        special_extensions = str_to_list(special_extensions)

    detect_relevant_tests(
        project_name,
        coverage_dir,
        git_diff_use_head,
        special_files,
        special_extensions,
        output_file,
        compare_to_branch,
        line_coverage,
    )


if __name__ == "__main__":
    main()
