from setuptools import setup, find_packages

setup(
    name="buslib",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.25.0",
        "pydantic>=2.0.0",
        "anthropic>=0.39.0",
    ],
)
