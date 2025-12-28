import sys

from glisse import DSLRunner, load_from_config, show_config

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


def main():
    # print("Hello from glisse!")
    branches = load_from_config()
    assert len(branches) >= 1, f"must have at least one branch {branches}"

    show_config()

    base = branches[0]
    runner = DSLRunner(base)
    if "--undo" in sys.argv:
        runner.unwind()
    else:
        runner.execute()


if __name__ == "__main__":
    main()
