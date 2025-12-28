import sys

from glisse import DSLRunner

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
    runner = DSLRunner()
    runner.show_config()
    if "--undo" in sys.argv:
        runner.unwind()
    else:
        runner.execute()


if __name__ == "__main__":
    main()
