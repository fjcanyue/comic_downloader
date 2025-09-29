# Builds

This project uses standard Python packaging tools to create distributions.

## Building the project

1.  Ensure you have the latest version of `build` installed:

    ```bash
    pip install --upgrade build
    ```

2.  From the root of the project directory, run the following command:

    ```bash
    python -m build
    ```

This will create a `dist` directory containing the built packages (a `.whl` file and a `.tar.gz` file).
