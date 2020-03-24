import logging
import sqlite3
import sys
from collections import namedtuple
from contextlib import contextmanager
from glob import glob
from unittest.mock import patch

import pytest

from partialtesting import partialtesting as pt

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

FAKE_PROJECT = "fake_project"
TESTFILESDIR = "tests/integration/testfiles/"
GEN_TESTS_PATH = f"{TESTFILESDIR}generated_testfiles/"
FAKE_TESTS_PATH = f"{TESTFILESDIR}fake_testfiles/"
FAKE_COV_PATH = f"{TESTFILESDIR}{FAKE_PROJECT}/build_dir/"


def create_test_files(testfiles_dict):
    for testfilename, testnames in testfiles_dict.items():
        content = ""

        for testname in testnames:
            content += f"def {testname}():\n    pass\n\n"

        with open(f"{GEN_TESTS_PATH}{testfilename}", "w") as f:
            f.write(content)


def create_a_test_coverage_db(db_name):
    """
    SQL tables based on:
    https://github.com/nedbat/coveragepy/blob/c49e739380095a6939ab135626dbedf166204d58/doc/dbschema.rst
    https://nedbatchelder.com/blog/201810/who_tests_what_is_here.html
    https://nedbatchelder.com/blog/201612/who_tests_what.html
    """

    db_path = f"{FAKE_COV_PATH}/{db_name}"
    cleanup_test_db_and_files(db_path)

    db = sqlite3.connect(db_path)
    cursor = db.cursor()

    # Create the tables that coveragepy uses
    cursor.execute("CREATE TABLE coverage_schema ( version integer );")
    cursor.execute(
        "CREATE TABLE meta ( has_lines boolean, has_arcs boolean, sys_argv text );"
    )
    cursor.execute(
        "CREATE TABLE file ( id integer primary key, path text, unique(path) );"
    )
    cursor.execute(
        "CREATE TABLE context ( id integer primary key, context text, unique(context) );"
    )
    cursor.execute(
        "CREATE TABLE line ( file_id integer, context_id integer, lineno integer, unique(file_id, context_id, lineno) );"
    )
    cursor.execute(
        "CREATE TABLE arc ( file_id integer, context_id integer, fromno integer, tono integer, unique(file_id, context_id, fromno, tono) );"
    )
    cursor.execute("CREATE TABLE tracer ( file_id integer primary key, tracer text );")

    # Add a non-test source file
    nontestfile1_id = 1
    nontestfile2_id = 2
    nontestfile3_id = 3
    testfile1_id = 4
    cursor.execute(
        f"INSERT INTO file(id, path) VALUES"
        f"({nontestfile1_id}, 'nontestfile1.py'),"
        f"({nontestfile2_id}, 'nontestfile2.py'),"
        f"({nontestfile3_id}, 'nontestfile3.py'),"
        f"({testfile1_id}, 'tests/test_utility_file1.py');"
    )

    # Add contexts (test names in this case)
    cursor.execute(
        "INSERT INTO context(id, context) VALUES"
        "(1, 'test_testfile1_test1'),"
        "(2, 'test_testfile2_test1'),"
        "(3, 'test_testfile2_test2'),"
        "(4, 'test_testfile2_test3')"
        ";"
    )

    # create test files containing those test names
    create_test_files(
        {
            "test_testfile1.py": ["test_testfile1_test1"],
            "test_testfile2.py": [
                "test_testfile2_test1",
                "test_testfile2_test3",
                "test_testfile2_test3",
            ],
            "test_testfile3.py": [],
        }
    )

    # Link the contexts to the non-test source files to indicate which tests are triggered from which files
    any_number = "7"
    cursor.execute(
        f"INSERT INTO arc(file_id, context_id, fromno, tono) VALUES"
        # changes in nontestfile1.py trigger tests in testfile1
        f"({nontestfile1_id}, 1, {any_number}, {any_number}),"  # test named test_testfile1_test1
        # changes in nontestfile2.py trigger tests in testfile1, testfile2
        f"({nontestfile2_id}, 1, {any_number}, {any_number}),"  # test named test_testfile1_test1
        f"({nontestfile2_id}, 2, {any_number}, {any_number}),"  # test named test_testfile2_test1
        f"({nontestfile2_id}, 3, {any_number}, {any_number}),"  # test named test_testfile2_test2
        # changes nontestfile3.py trigger no tests
        # changes to test_utility_file1.py trigger tests in testfile1
        f"({testfile1_id}, 1, {any_number}, {any_number})"
        ";"
    )

    db.commit()

    return db_path


def cleanup_test_db_and_files(db_path):
    pt.run_sh_cmd(["rm", db_path])
    pt.run_sh_cmd(["rm"] + glob(f"{GEN_TESTS_PATH}test_*"))


def init_test_db_and_files():
    name = "test_db_1"
    db_path = create_a_test_coverage_db("test_db_1")

    DBinfo = namedtuple("DBinfo", "name path")
    return name, db_path, DBinfo


@pytest.fixture(scope="function")
def generated_db():
    name, db_path, DBinfo = init_test_db_and_files()
    yield DBinfo(name, db_path)
    cleanup_test_db_and_files(db_path)


@contextmanager
def generated_db_ctx_mgr():
    """
    Same as generate_db() above, but pytest does
    not allow combining pytest-fixtures with pytest.parametrize
    so using a standard context manager for that
    """
    name, db_path, DBinfo = init_test_db_and_files()
    yield DBinfo(name, db_path)
    cleanup_test_db_and_files(db_path)


def test_get_last_build_directory(generated_db):

    last_build_db_name = pt.get_last_build_directory(f"{FAKE_COV_PATH}")
    assert last_build_db_name == generated_db.name


def test_connect_to_db(generated_db):

    # Connecting to this local file should not fail
    db, cursor = pt.connect_to_db(generated_db.path)

    sql_query = f""" select * from file """
    cursor.execute(sql_query, ())

    rows = list(cursor.fetchall())
    assert len(rows) > 0


def test_db_get_test_names_for_file(generated_db):

    # check that we get the correct tests for the nontest files
    assert pt.get_tests_that_use_file("nontestfile1.py", generated_db.path) == [
        "test_testfile1_test1"
    ]
    assert pt.get_tests_that_use_file("nontestfile2.py", generated_db.path) == [
        "test_testfile1_test1",
        "test_testfile2_test1",
        "test_testfile2_test2",
    ]
    assert pt.get_tests_that_use_file("nontestfile3.py", generated_db.path) == []


def test_end_to_end_new_source_triggers_fulltest(generated_db):

    # diff with new (A=added) file
    git_diff = f"""\
A nontestfile1.py
"""

    with patch("partialtesting.partialtesting.COVERAGE_FILE", generated_db.path):
        with patch(
            "partialtesting.partialtesting.git_diff_namestatus", return_value=git_diff
        ):

            test_files = pt.detect_relevant_tests(
                project_name=FAKE_PROJECT,
                coverage_dir=TESTFILESDIR,
                git_diff_use_head=True,
            )
            assert test_files is None  # full test is required


def test_end_to_end_modified_source_file_triggers_partialtesting(generated_db):

    # diff with modified (M) file
    git_diff = f"""\
M nontestfile1.py
"""

    with patch("partialtesting.partialtesting.COVERAGE_FILE", generated_db.name):
        with patch(
            "partialtesting.partialtesting.git_diff_namestatus", return_value=git_diff
        ):

            test_files = pt.detect_relevant_tests(
                project_name=FAKE_PROJECT,
                coverage_dir=TESTFILESDIR,
                git_diff_use_head=True,
            )

            assert f"{GEN_TESTS_PATH}test_testfile1.py" in test_files


@pytest.mark.parametrize("status", [("A"), ("M")])
def test_end_to_end_new_or_modified_test_file_triggers_partialtesting(status):

    with generated_db_ctx_mgr() as gen_db:
        test_file = f"{TESTFILESDIR}test_any_test_file_in_tests_dir.py"
        git_diff = f"""\
{status} {test_file}
"""
        with patch("partialtesting.partialtesting.COVERAGE_FILE", gen_db.name):
            with patch(
                "partialtesting.partialtesting.git_diff_namestatus",
                return_value=git_diff,
            ):

                test_files = pt.detect_relevant_tests(
                    project_name=FAKE_PROJECT,
                    coverage_dir=TESTFILESDIR,
                    git_diff_use_head=True,
                )
                assert test_files == {test_file}


def test_end_to_end_deleted_test_file_no_tests(generated_db):

    git_diff = f"""\
D tests/unit/storage/test_storage.py
"""

    with patch("partialtesting.partialtesting.COVERAGE_FILE", generated_db.name):
        with patch(
            "partialtesting.partialtesting.git_diff_namestatus", return_value=git_diff
        ):

            test_files = pt.detect_relevant_tests(
                project_name=FAKE_PROJECT,
                coverage_dir=TESTFILESDIR,
                git_diff_use_head=True,
            )
            assert test_files is not None  # not full test

            # partial test enabled but no tests to run - empty set
            assert test_files == set()


@pytest.mark.parametrize(
    "status,file",
    [
        ("M", "setup.cfg"),
        ("A", "setup.cfg"),
        ("M", "some/directory/pickled.p"),
        ("M", "some/directory/pickled.pkl"),
        ("M", "some/directory/pickled.h5"),
        ("A", "tests/some/directory/pickled.h5"),
        ("A", "tests/some/directory/fxcurve.png"),
        ("M", "tests/some/directory/conftest.py"),
    ],
)
def test_end_to_end_modified_special_file_triggers_fulltest(status, file):

    with generated_db_ctx_mgr() as gen_db:

        git_diff = f"""\
{status} {file}
"""

        with patch("partialtesting.partialtesting.COVERAGE_FILE", gen_db.name):
            with patch(
                "partialtesting.partialtesting.git_diff_namestatus",
                return_value=git_diff,
            ):

                test_files = pt.detect_relevant_tests(
                    project_name=FAKE_PROJECT,
                    coverage_dir=TESTFILESDIR,
                    git_diff_use_head=True,
                )
                assert test_files is None


@pytest.mark.parametrize("status,file", [("M", "README.md"), ("A", "README.md")])
def test_end_to_end_readme_file_notests(status, file):

    with generated_db_ctx_mgr() as gen_db:

        git_diff = f"""\
{status} {file}
"""

        with patch("partialtesting.partialtesting.COVERAGE_FILE", gen_db.name):
            with patch(
                "partialtesting.partialtesting.git_diff_namestatus",
                return_value=git_diff,
            ):

                test_files = pt.detect_relevant_tests(
                    project_name=FAKE_PROJECT,
                    coverage_dir=TESTFILESDIR,
                    git_diff_use_head=True,
                )
                assert test_files is not None  # None is for fulltest

                # partial test enabled but no tests to run - empty set
                assert test_files == set()


def test_end_to_end_multiple_files(generated_db):

    git_diff = f"""\
M nontestfile1.py
M nontestfile2.py
A {GEN_TESTS_PATH}test_testfile1.py
M {GEN_TESTS_PATH}test_testfile1.py
A readme.md
"""

    with patch("partialtesting.partialtesting.COVERAGE_FILE", generated_db.name):
        with patch(
            "partialtesting.partialtesting.git_diff_namestatus", return_value=git_diff
        ):

            test_files = pt.detect_relevant_tests(
                project_name=FAKE_PROJECT,
                coverage_dir=TESTFILESDIR,
                git_diff_use_head=True,
            )

            assert f"{GEN_TESTS_PATH}test_testfile1.py" in test_files
            assert f"{GEN_TESTS_PATH}test_testfile2.py" in test_files


def test_end_to_end_bad_directory_doesnt_fail_script_instead_triggers_fulltest():
    test_files = pt.detect_relevant_tests(
        "NONEXISTENT_PROJECT", coverage_dir=f"{TESTFILESDIR}", git_diff_use_head=True
    )
    assert test_files is None  # full test is required


def test_detect_files_to_test_1():
    """
    test that we correctly detect where (in which file) tests are defined
    based on the test name: test_fakename_2
    """

    expected_files = sorted(
        [
            f"{FAKE_TESTS_PATH}test_file_a.py",
            f"{FAKE_TESTS_PATH}test_file_c.py",
            f"{FAKE_TESTS_PATH}test_file_e.py",
        ]
    )

    assert (
        sorted(
            pt.get_test_files_for_test_names(
                ["test_fakename_2"], tests_dir=f"{TESTFILESDIR}"
            )
        )
        == expected_files
    )


def test_detect_files_to_test_2():
    """
    test that we correctly detect where (in which file) tests are defined
    based on the test name: test_fakename_9
    """

    expected_files = sorted([f"{FAKE_TESTS_PATH}test_file_e.py"])

    assert (
        sorted(
            pt.get_test_files_for_test_names(
                ["test_fakename_9"], tests_dir=f"{TESTFILESDIR}"
            )
        )
        == expected_files
    )


def test_detect_files_to_test_using_fully_qualified_tests():
    """
    test that we correctly detect where (in which file) tests are defined
    even for fully qualified tests names coverage (version >= v5.0a6)
    https://github.com/nedbat/coveragepy/commit/a9f5f7fadacaa8a84b4ac247e79bcb6f29935bb1
    """

    assert sorted(
        pt.get_test_files_for_test_names(
            [
                "tests.unit.fake_module.FakeClass.test_fakename_9"
            ],  # Fully qualified test names
            tests_dir=f"{TESTFILESDIR}",
        )
    ) == [f"{FAKE_TESTS_PATH}test_file_e.py"]


def test_identify_files_to_test_for_modified_files(generated_db):
    """
    Check that if a nontest file doesnt trigger any tests files
    the script doesnt error out
    """

    project = pt.Project("fake_project", coverage_dir="", build_number="784")
    project.coverage_db_path = generated_db.path

    result = pt.identify_files_to_test_for_modified_files(
        [pt.File("fake_dir/fake_file.py", "A")], project
    )
    assert len(result) == 0


def test_end_to_end_with_renamed_test_file(generated_db):
    """
    When test files are renamed, the new name should be given to pytest

    generated_db creates a testfile 'test_testfile1.py' with a test named 'test_testfile1_test1'
    and 'nontestfile1.py' triggers test 'test_testfile1_test1', so even if the rename line in git_diff
    wasnt there
    """
    old_testfile_name = f"{GEN_TESTS_PATH}test_testfile1.py"
    new_testfile_name = f"{GEN_TESTS_PATH}test_testfile_new_name.py"

    git_diff = f"""\
M nontestfile1.py
R100 {old_testfile_name} {new_testfile_name}
A {GEN_TESTS_PATH}test_testfile2.py
"""

    # move the file test_testfile1.py to simulate renaming
    pt.run_sh_cmd(["mv", f"{old_testfile_name}", f"{new_testfile_name}"])

    with patch("partialtesting.partialtesting.COVERAGE_FILE", generated_db.name), patch(
        "partialtesting.partialtesting.git_diff_namestatus", return_value=git_diff
    ):

        test_files = pt.detect_relevant_tests(
            project_name=FAKE_PROJECT, coverage_dir=TESTFILESDIR, git_diff_use_head=True
        )

        assert old_testfile_name not in test_files
        assert new_testfile_name in test_files
        assert f"{GEN_TESTS_PATH}test_testfile2.py" in test_files


def test_end_to_end_modified_test_utility_file(generated_db):
    """
    A file under tests/ (test file) can also be a utility file,
    that is, a file that is imported and used when running tests.
    So, when a test utility file is modified, it should trigger
    a run of those related tests

    From the generated_db fixture:
    test_utility_file1.py ---triggers--> test_testfile1_test1
    which is in test_testfile1.py
    """

    git_diff = f"""\
M tests/test_utility_file1.py
"""

    with patch("partialtesting.partialtesting.COVERAGE_FILE", generated_db.name):
        with patch(
            "partialtesting.partialtesting.git_diff_namestatus", return_value=git_diff
        ):

            test_files = pt.detect_relevant_tests(
                project_name=FAKE_PROJECT,
                coverage_dir=TESTFILESDIR,
                git_diff_use_head=True,
            )

            assert f"{GEN_TESTS_PATH}test_testfile1.py" in test_files
