from setuptools import setup, find_packages
from os import path

# The directory containing this file
HERE = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(HERE, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

with open(path.join(HERE, "requirements.txt")) as f:
    required = f.read().splitlines()

setup(
    name="kibernikto",
    version="1.5.3",
    packages=find_packages(),
    install_requires=required,
    url='https://github.com/solovieff/kibernikto',
    license='GPL-3.0 license',
    author_email='solovieff.nnov@gmail.com',
    description='Easily run telegram bots connected to AI models.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent"
    ],
    entry_points={
        "console_scripts": [
            "kibernikto=kibernikto.cmd.__start:start",
        ]
    },
)
