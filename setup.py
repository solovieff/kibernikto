from setuptools import setup, find_packages

with open("requirements.txt") as f:
    required = f.read().splitlines()

with open("README.md", encoding='utf-8') as f:
    long_description = f.read()
setup(
    name="kibernikto",
    version="1.0.10",
    packages=find_packages(),
    install_requires=required,
    url='https://github.com/solovieff/kibernikto',
    license='GPL-3.0 license',
    author_email='solovieff.nnov@gmail.com',
    description='easily run telegram bots connected to AI models.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Operating System :: OS Independent"
    ],
    entry_points={
        "console_scripts": [
            "kibernikto=kibernikto.cmd.__start:start",
        ]
    },
)
