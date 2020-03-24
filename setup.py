#!/usr/bin/env python
from os import path

from setuptools import setup

# get long_description from README.md
here = path.abspath(path.dirname(__file__))
with open(path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()


setup(
    name="partialtesting",
    version="1.0",
    author="MAN Alpha Technology",
    author_email="ManAlphaTech@man.com",
    packages=['partialtesting'],
    description="Partial Testing: run only the tests relevant to your changes",
    license="GPLv3+",
    long_description=long_description,
    keywords=["testing", "coverage", "partialtesting"],
    url="https://github.com/man-group/partialtesting",
    zip_safe=False,
    install_requires=["click",],
    extras_require={"tests": ["pytest"]},
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Software Development",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.8",
    ],
    entry_points={
        "console_scripts": [
            "partialtesting = partialtesting.partialtesting:main",
            "partialtest = partialtesting.partialtesting:main",
        ]
    },
)
