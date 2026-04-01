from setuptools import find_namespace_packages, setup


setup(
    name="cli-anything-eagle",
    version="0.1.0",
    description="CLI-Anything style harness for controlling Eagle through its local API.",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    install_requires=[
        "click>=8.1.0",
        "requests>=2.31.0",
    ],
    entry_points={
        "console_scripts": [
            "cli-anything-eagle=cli_anything.eagle.eagle_cli:main",
        ]
    },
)
