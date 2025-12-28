import sys

from glisse import DSLRunner, load_from_config

import typer

app = typer.Typer(no_args_is_help=True)

"""
branch("dev") > transition() > branch("staging") > transition() > branch("main")

# or

branch("dev") > branch("staging") > branch("main")

dev = branch("dev")
staging = branch("staging")
main = branch("main")

dev > staging > main

staging.when_merged(lambda ctx: os.exec("bumpversion --tag"))
main.when_merged(lambda ctx: os.exec("bumpversion --tag"))
"""

# prom repo promotion state
# prom-start br [a>b>c] nil
# prom a [a>b>c] nil
# prom-merge a b
# prom-eff (eff a b)
# prom b [b>c] [b':b]
# prom-merge b c
# prom-eff (eff b c)
# prom c [c] [c':c, b':b]
# prom-end c [c':c, b':b]

branches = load_from_config()
assert len(branches) >= 1, f"must have at least one branch {branches}"
base = branches[0]
runner = DSLRunner(base)

@app.command()
def run():
    """Merge the branches according to pyproject.toml."""
    runner.execute()

@app.command()
def undo():
    """Unmerge the branches according to ".merge_state.json"."""
    runner.unwind()

if __name__ == "__main__":
    app()
