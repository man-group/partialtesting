import logging
import sys
from unittest.mock import ANY, patch

import pytest
from click.testing import CliRunner

from partialtesting import partialtesting as pt

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)


SOURCE_FILE_1 = "dir1/dir2/nontestfile1.py"
SOURCE_FILE_2 = "dir1/dir3/myfile2.py"
SOURCE_FILE_3 = "dir4/dir5/anotherfile3.py"

SPECIAL_FILE_1 = "setup.py"
SPECIAL_FILE_2 = "setup_ts2.py"

SPECIAL_EXT_FILE_1 = "dir1/data/fake_image.png"
SPECIAL_EXT_FILE_2 = "dir2/pickles/fake_pickle.pkl"
SPECIAL_EXT_FILE_3 = "dir3/data/fake_h5.h5"

TEST_FILE_UNIT_1 = "tests/unit/test_unit1.py"
TEST_FILE_UNIT_2 = "tests/unit/test_unit2.py"
TEST_FILE_INTEGRATION_1 = "tests/integration/test_int_1.py"
TEST_FILE_INTEGRATION_2 = "tests/integration/test_int_2.py"
TEST_FILE_INTEGRATION_DB_1 = "tests/integration_db/test_int_db_1.py"
TEST_FILE_INTEGRATION_DB_2 = "tests/integration_db/test_int_db_2.py"

FILE_OF_UNKNOWN_TYPE = "security_master/equity_asia1.out.gz.enc.20180827"
TEST_FILE_OF_UNKNOWN_TYPE = f"tests/integration/{FILE_OF_UNKNOWN_TYPE}"

README_FILE = "README.md"


@pytest.mark.parametrize(
    "git_status,internal_status",
    [
        ("A", pt.FileStatus.ADDED),
        ("D", pt.FileStatus.DELETED),
        ("M", pt.FileStatus.MODIFIED),
        ("B", pt.FileStatus.OTHER),
        ("R084", pt.FileStatus.RENAMED),
        ("R100", pt.FileStatus.RENAMED),
    ],
)
def test_parse_git_diff_name_status(git_status, internal_status):

    new_file = f"""\
{git_status} {SOURCE_FILE_1}
"""

    files = pt.parse_git_diff_name_status(new_file)

    assert len(files) == 1
    assert files[0].path == SOURCE_FILE_1
    assert files[0].status == internal_status
    assert files[0].is_test_file() is False


def test_parse_git_diff_name_status_multiple():

    git_status_output = f"""\
A {SOURCE_FILE_1}
D {SOURCE_FILE_2}
M {TEST_FILE_UNIT_1}
B {TEST_FILE_INTEGRATION_1}
A {TEST_FILE_INTEGRATION_DB_1}
"""

    files = pt.parse_git_diff_name_status(git_status_output)

    assert len(files) == 5

    assert files[0].path == SOURCE_FILE_1
    assert files[0].status == pt.FileStatus.ADDED
    assert files[0].is_test_file() is False

    assert files[1].path == SOURCE_FILE_2
    assert files[1].status == pt.FileStatus.DELETED
    assert files[1].is_test_file() is False

    assert files[2].path == TEST_FILE_UNIT_1
    assert files[2].status == pt.FileStatus.MODIFIED
    assert files[2].is_test_file() is True

    assert files[3].path == TEST_FILE_INTEGRATION_1
    assert files[3].status == pt.FileStatus.OTHER
    assert files[3].is_test_file() is True

    assert files[4].path == TEST_FILE_INTEGRATION_DB_1
    assert files[4].status == pt.FileStatus.ADDED
    assert files[4].is_test_file() is True


def test_parse_git_diff_name_status_renamed():
    """
    renamed files have a different format, with a status and 2 file paths:
    R084    tests/regression/mkd/tools/scripts/test_compare_sql.py  tests/integration/mkd/tools/scripts/test_compare_sql.py
    """

    code_file_old_name = "dir1/dir2/file_old.py"
    code_file_new_name = "dir1/dir3/file_new.py"

    # if a test file is renamed/moved, only the new name should be passed to pytest
    test_file_old_path_1 = "tests/regression/mkd/tools/scripts/test_compare_sql.py"
    test_file_new_path_1 = "tests/integration/mkd/tools/scripts/test_compare_sql.py"

    old_path_2 = ".project"
    new_path_2 = "fer_project"

    git_status_output = f"""\
R091    {code_file_old_name} {code_file_new_name}
R084    {test_file_old_path_1}  {test_file_new_path_1}
M       dir1/dir2/scripts/app.py
R100    {old_path_2}        {new_path_2}
"""

    files = pt.parse_git_diff_name_status(git_status_output)

    assert len(files) == 4

    assert files[0].path == code_file_old_name
    assert files[0].status == pt.FileStatus.RENAMED
    assert files[0].is_test_file() is False

    assert files[1].path == test_file_old_path_1
    assert files[1].status == pt.FileStatus.RENAMED
    assert files[1].is_test_file() is True

    assert files[3].path == old_path_2
    assert files[3].status == pt.FileStatus.RENAMED
    assert files[3].is_test_file() is False


def test_renamed_test_files():

    test_file_old_path_1 = "tests/unit/test_file.py"
    test_file_new_path_1 = "tests/integration/test_file.py"

    test_file_old_path_2 = "tests/unit/test_old_name.py"
    test_file_new_path_2 = "tests/unit/test_new_name.py"

    git_status_output = f"""\
R091 {test_file_old_path_1} {test_file_new_path_1}
A file_a.py
R100 {test_file_old_path_2} {test_file_new_path_2}
D file_b.py
"""

    files = pt.parse_git_diff_name_status(git_status_output)

    renamed_test_files = []
    for file in files:
        if file.path == test_file_old_path_1:
            assert file.new_path == test_file_new_path_1
            assert file.status == pt.FileStatus.RENAMED
            renamed_test_files.append(file)
        elif file.path == test_file_old_path_2:
            assert file.new_path == test_file_new_path_2
            assert file.status == pt.FileStatus.RENAMED
            renamed_test_files.append(file)
        else:
            assert file.new_path is None

    assert len(renamed_test_files) == 2

    files_to_test = pt.identify_files_to_test_for_testfiles(renamed_test_files)

    # check that only the new paths (after rename) are going to be run/tested
    assert sorted(files_to_test) == sorted([test_file_new_path_1, test_file_new_path_2])


def test_new_nontest_code_file_added():

    assert pt.new_nontest_code_file_added([pt.File(SOURCE_FILE_1, "A")]) is True

    assert pt.new_nontest_code_file_added([pt.File(SOURCE_FILE_1, "M")]) is False

    assert (
        pt.new_nontest_code_file_added(
            [
                pt.File(SOURCE_FILE_1, "M"),
                pt.File(SOURCE_FILE_2, "D"),
                pt.File(SOURCE_FILE_3, "A"),
            ]
        )
        is True
    )

    assert (
        pt.new_nontest_code_file_added(
            [
                pt.File(SOURCE_FILE_1, "M"),
                pt.File(SOURCE_FILE_2, "D"),
                pt.File(SOURCE_FILE_3, "B"),
            ]
        )
        is False
    )

    assert pt.new_nontest_code_file_added([pt.File(README_FILE, "A")]) is False


@pytest.mark.parametrize("filestatus", [("A"), ("M"), ("D"), ("B")])
def test_modified_special_file(filestatus):

    assert (
        pt.modified_special_file(
            [pt.File(SOURCE_FILE_1, filestatus)], pt.SPECIAL_FILES_DEFAULT
        )
        is False
    )

    assert (
        pt.modified_special_file(
            [pt.File(SPECIAL_FILE_1, filestatus)], pt.SPECIAL_FILES_DEFAULT
        )
        is True
    )

    assert (
        pt.modified_special_file(
            [pt.File(SPECIAL_FILE_2, filestatus)], pt.SPECIAL_FILES_DEFAULT
        )
        is True
    )

    assert (
        pt.modified_special_file(
            [pt.File(SPECIAL_EXT_FILE_1, filestatus)], pt.SPECIAL_FILES_DEFAULT
        )
        is False
    )

    assert (
        pt.modified_special_file(
            [pt.File(TEST_FILE_UNIT_1, filestatus)], pt.SPECIAL_FILES_DEFAULT
        )
        is False
    )


@pytest.mark.parametrize("filestatus", [("A"), ("M"), ("D"), ("B")])
def test_modified_file_with_special_extension(filestatus):

    assert (
        pt.modified_file_with_special_or_unknown_extension(
            [pt.File(SOURCE_FILE_1, filestatus)], pt.SPECIAL_EXTENSIONS_DEFAULT
        )
        is False
    )

    assert (
        pt.modified_file_with_special_or_unknown_extension(
            [pt.File(SPECIAL_FILE_1, filestatus)], pt.SPECIAL_EXTENSIONS_DEFAULT
        )
        is False
    )

    assert (
        pt.modified_file_with_special_or_unknown_extension(
            [pt.File(SPECIAL_EXT_FILE_1, filestatus)], pt.SPECIAL_EXTENSIONS_DEFAULT
        )
        is True
    )

    assert (
        pt.modified_file_with_special_or_unknown_extension(
            [pt.File(SPECIAL_EXT_FILE_2, filestatus)], pt.SPECIAL_EXTENSIONS_DEFAULT
        )
        is True
    )

    assert (
        pt.modified_file_with_special_or_unknown_extension(
            [pt.File(SPECIAL_EXT_FILE_3, filestatus)], pt.SPECIAL_EXTENSIONS_DEFAULT
        )
        is True
    )

    assert (
        pt.modified_file_with_special_or_unknown_extension(
            [pt.File(TEST_FILE_UNIT_1, filestatus)], pt.SPECIAL_EXTENSIONS_DEFAULT
        )
        is False
    )


def test_is_full_test_required():

    # changing non-special files. Only added should trigger full test

    assert (
        pt.full_test_required(
            [pt.File(SOURCE_FILE_1, "A")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )
    assert (
        pt.full_test_required(
            [pt.File(SOURCE_FILE_1, "M")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is False
    )
    assert (
        pt.full_test_required(
            [pt.File(SOURCE_FILE_1, "D")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is False
    )

    # changing non-special test files.
    assert (
        pt.full_test_required(
            [],
            [pt.File(TEST_FILE_UNIT_1, "A")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is False
    )
    assert (
        pt.full_test_required(
            [],
            [pt.File(TEST_FILE_INTEGRATION_1, "A")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is False
    )
    assert (
        pt.full_test_required(
            [],
            [pt.File(TEST_FILE_INTEGRATION_DB_1, "A")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is False
    )

    # changing special files triggers full test

    assert (
        pt.full_test_required(
            [pt.File(SPECIAL_FILE_1, "M")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )
    assert (
        pt.full_test_required(
            [],
            [pt.File(SPECIAL_FILE_1, "M")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )

    # changing special extension files triggers full test

    assert (
        pt.full_test_required(
            [pt.File(SPECIAL_EXT_FILE_1, "M")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )
    assert (
        pt.full_test_required(
            [],
            [pt.File(SPECIAL_EXT_FILE_1, "M")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )

    # File of unknown type
    assert (
        pt.full_test_required(
            [pt.File(FILE_OF_UNKNOWN_TYPE, "A")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )
    assert (
        pt.full_test_required(
            [pt.File(FILE_OF_UNKNOWN_TYPE, "M")],
            [],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )

    # Test File of unknown type
    assert (
        pt.full_test_required(
            [],
            [pt.File(TEST_FILE_OF_UNKNOWN_TYPE, "A")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )
    assert (
        pt.full_test_required(
            [],
            [pt.File(TEST_FILE_OF_UNKNOWN_TYPE, "M")],
            pt.SPECIAL_FILES_DEFAULT,
            pt.SPECIAL_EXTENSIONS_DEFAULT,
        )
        is True
    )


def test_identify_files_to_test_for_testfiles():

    assert pt.identify_files_to_test_for_testfiles([]) == []

    added_1 = pt.File(TEST_FILE_UNIT_1, "A")
    added_2 = pt.File(TEST_FILE_UNIT_2, "A")
    deleted_1 = pt.File(TEST_FILE_UNIT_1, "D")

    assert pt.identify_files_to_test_for_testfiles([added_1]) == [TEST_FILE_UNIT_1]

    assert pt.identify_files_to_test_for_testfiles([added_1, added_2, deleted_1]) == [
        TEST_FILE_UNIT_1,
        TEST_FILE_UNIT_2,
    ]

    assert pt.identify_files_to_test_for_testfiles([deleted_1, added_2]) == [
        TEST_FILE_UNIT_2
    ]


def test_strtolist():

    assert ["file1", "file2.py", "file3.cfg", "image.png"] == pt.str_to_list(
        """[file1, file2.py, file3.cfg, image.png]"""
    )
    assert ["file1", "file2"] == pt.str_to_list("""file1,file2""")


def test_cli_args():
    # Setup
    runner = CliRunner()

    with patch.object(
        pt, pt.detect_relevant_tests.__name__, autospec=True
    ) as mock_detect_relevant_tests:
        # Execute
        result = runner.invoke(
            pt.main,
            args=[
                "--project-name",
                "helloworld",
                "--coverage-dir",
                "/coverage_dir",
                "--git-diff-use-head",
                "--special-files",
                "[special_file_1, special_file_2]",
                "--special-extensions",
                "[special_ext_1, special_ext_2]",
                "--output-file",
                "my_out_file",
                "--compare-to-branch",
                "my_custom_branch",
                "--line-coverage",
            ],
            catch_exceptions=False,
        )

        print(result.output)

    # Assert
    mock_detect_relevant_tests.assert_called_once_with(
        "helloworld",
        "/coverage_dir",
        True,
        ["special_file_1", "special_file_2"],
        ["special_ext_1", "special_ext_2"],
        "my_out_file",
        "my_custom_branch",
        True,
    )


@pytest.mark.parametrize("flag_applied", [True, False])
def test_cli_args_git_diff_use_head_flag(flag_applied):
    # Setup
    runner = CliRunner()

    args = ["--project-name", "helloworld2", "--coverage-dir", "/coverage_dir"]

    if flag_applied:
        args.append("--git-diff-use-head")
        args.append("--line-coverage")

    with patch.object(
        pt, pt.detect_relevant_tests.__name__, autospec=True
    ) as mock_detect_relevant_tests:
        # Execute
        runner.invoke(pt.main, args, catch_exceptions=False)

    # Assert
    mock_detect_relevant_tests.assert_called_once_with(
        ANY, ANY, flag_applied, ANY, ANY, ANY, ANY, flag_applied
    )
