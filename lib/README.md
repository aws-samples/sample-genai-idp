# Common Libraries for Intelligent Document Processing

This directory contains common Python packages that are shared across the IDP accelerator. These packages can be independently installed and provide reusable functionality for different components of the solution.

## Available Packages

- **appsync_helper_pkg**: Helper utilities for working with AppSync GraphQL APIs
- **get_config_pkg**: Common configuration management for IDP components

## Adding a New Package

To add a new shared package, follow these steps:

1. Create a new directory for your package with a descriptive name, following the naming convention `package_name_pkg`

2. Inside your package directory, create:
   - A Python module directory (e.g., `my_module/`)
   - `setup.py` file for installation
   - `pyproject.toml` for build configuration
   - `README.md` explaining the package's purpose and usage

3. Basic package structure:
   ```
   your_package_pkg/
   ├── README.md
   ├── your_module/
   │   └── __init__.py
   ├── pyproject.toml
   └── setup.py
   ```

4. Example setup.py:
   ```python
   from setuptools import setup, find_packages

   setup(
       name="idp-your-package-name",
       version="0.1.0",
       packages=find_packages(),
       install_requires=[
           # List dependencies here
           "boto3",
       ],
   )
   ```

5. Example pyproject.toml:
   ```toml
   [build-system]
   requires = ["setuptools>=42", "wheel"]
   build-backend = "setuptools.build_meta"
   ```

6. After creating your package, build it with:
   ```
   cd your_package_pkg
   pip install -e .
   ```

7. To use the package in Lambda functions, include it in the `requirements.txt` file:
   ```
   idp-your-package-name==0.1.0
   ```

## Best Practices

- Keep packages focused on a specific functionality
- Include proper documentation in your package's README.md
- Follow Python best practices with type hints and docstrings
- Write unit tests for your package functionality
- Include copyright notice in file headers