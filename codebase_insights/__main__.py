# Makes `python -m codebase_insights <repo_path> ...` work -- Python runs
# this file when a package is invoked with -m. Deliberately a one-liner:
# all real logic lives in cli.py/runner.py, this file just wires the two
# together and turns cli.main()'s return code into the process's actual
# exit code.
from .cli import main

raise SystemExit(main())
