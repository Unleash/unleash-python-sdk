****************************************
Development
****************************************

Contributions welcome!

Here are some notes about common tools and tasks you'll run into when working on `unleash-python-sdk`.

Tooling
#######################################

- `Pyenv <https://github.com/pyenv/pyenv>`_ for managing Python versions.
- `ruff <https://github.com/charliermarsh/ruff>`_ for linting.
- `black <https://github.com/psf/black>`_ for formatting.

Testing
#######################################

1. Activate your virtualenv solution (e.g. `source activate YOUR_VIRTUALENV`).
2. Run linting & tests: ``make test``

Running Tox locally
#######################################
1. Install Python versions for each supported version.
2. Deactivate your local virtualenv (if it's activated).
3. Run ``pyenv local 3.13.X 3.12.X 3.11.X 3.10.X 3.9.Y 3.8.Z`` (inserting appropriate patch versions).
4. Run ``make install`` to get latest local dependencies.
5. Run ``make tox`` to run tox.

Using devcontainer
###########################################
This SDK ships with a devcontainer to make local (or cloud!) environment fast & easy!

Upgrading the Client Specification Tests
###########################################
This SDK implements tests for the `Unleash Client Specifications <https://github.com/Unleash/client-specification>`_,
when adding a new feature set that's covered by the client specs, it's a good idea to also upgrade the client specifications.
This can be done by updating the ``CLIENT_SPEC_VERSION`` constant found in ``UnleashClient/constants.py``.
This constant should match the latest tag in the Client Specifications repository.


Release
#######################################

1. Land all your PRs on `main`!
2. If new configuration is added, update `Flask-Unleash <https://github.com/Unleash/Flask-Unleash>`_ config.
3. Update changelog.md and other documentation.
4. Create tag on `main` branch.
5. Create new Release in Github and paste in changelog.
6. Github Actions workflow will automagically publish to Pypi and build documentation.
7. Publish new Flask-Unleash package (if necessary).

Snippets
#######################################

Serving docs from WSL!

.. code-block:: shell

    docker run -d --name unleash-docs --rm -v `pwd`/_build/html:/web -p 8080:8080 halverneus/static-file-server:latest
