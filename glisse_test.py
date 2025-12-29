from glisse import Branch #, DSLRunner

def test_branch_order():
    """The `>` operator must order branches from left to right."""
    dev = Branch("dev")
    staging = Branch("staging")
    main = Branch("main")
    _ = dev > staging > main
    print(dev, staging, main)
    assert dev.next_branch == staging, "assert dev > staging"
    assert staging.next_branch == main, "assert staging > main"
