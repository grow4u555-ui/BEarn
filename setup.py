from setuptools import setup, find_packages

setup(
    name="bearn",
    version="0.1.0",
    description="BEarn — Live Earning System via Proxy Traffic",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "stripe>=7.0.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "bearn=src.cli:main",
        ],
    },
)
