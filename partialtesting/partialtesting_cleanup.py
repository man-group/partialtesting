import logging
import os
import sys

import click

import partialtesting as pt

DEFAULT_COVERAGE_DIR = "default_dir"


def clean_coverage_data(coverage_dir, branch):
    """
    Utility function to remove old .coverage files.
    Keeping the newest coverage file is enough.
    """
    for root, dirs, files in os.walk(coverage_dir):
        if root.endswith(f"/{branch}"):
            last_build = pt.get_last_build_number(root)
            logging.info(
                f"At {root} the last build is: {last_build} and there are {len(dirs)} builds."
            )
            last_build_path = os.path.join(root, last_build)

            if os.path.isdir(last_build_path):  # safety check
                # Now that we know the last build dir, delete all others
                dirs.remove(last_build)
                for older_build in dirs:
                    older_build_path = os.path.join(root, older_build)
                    logging.info(f"Deleting: {older_build_path}")
                    stdout, stderr = pt.run_sh_cmd(["rm", "-rf", older_build_path])
                    if stdout or stderr:
                        logging.info(f"Stdout: '{stdout}' stderr: '{stderr}'")


@click.command()
@click.option(
    "--coverage-dir",
    default=DEFAULT_COVERAGE_DIR,
    help=f"Path to the saved coverage data to clean. Default: {DEFAULT_COVERAGE_DIR}",
)
@click.option(
    "--branch",
    default="master",
    help=f"Branch of builds to cleanup. Usually, the master branch is the only one"
    "that stores coverage data",
)
def main(coverage_dir, branch):

    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    logging.info(f"Will clean coverage data in {coverage_dir}")

    clean_coverage_data(coverage_dir, branch)


if __name__ == "__main__":
    main()
