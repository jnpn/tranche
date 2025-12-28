import os
import sys
import json
import subprocess
from dataclasses import dataclass, field, asdict
from typing import List, Callable, Dict

import functools
import toml

# --- eDSL Core ---

class Branch:
    def __init__(self, name: str):
        self.name = name
        self.hooks: List[Callable] = []
        self.next_branch: 'Optional[Branch]' = None

    def when_merged(self, func: Callable):
        self.hooks.append(func)
        return self

    def __gt__(self, other: 'Branch'):
        """Overloads the '>' operator to define order."""
        self.next_branch = other
        return other

    def __repr__(self):
        return f"Branch({self.name})"

# --- State Persistence (Same Logic as Phase 1) ---

@dataclass
class MergeStep:
    target_branch: str
    original_sha: str
    tags_created: List[str] = field(default_factory=list)

class DSLRunner:
    STATE_FILE = ".merge_state.json"

    def __init__(self, start_node: Branch):
        self.start_node = start_node
        self.history: List[MergeStep] = []

    def _get_pipeline(self) -> List[Branch]:
        nodes = []
        curr = self.start_node
        while curr:
            nodes.append(curr)
            curr = curr.next_branch
        return nodes

    def _save_state(self):
        with open(self.STATE_FILE, "w") as f:
            json.dump([asdict(s) for s in self.history], f, indent=2)

    def execute(self):
        pipeline = self._get_pipeline()

        for i in range(len(pipeline) - 1):
            src, tgt = pipeline[i], pipeline[i+1]
            print(f"\n>>> Merging {src.name} -> {tgt.name}")

            # Capture state
            pre_tags = self._get_tags()
            target_sha = self._get_sha(tgt.name)

            step = MergeStep(target_branch=tgt.name, original_sha=target_sha)
            self.history.append(step)
            self._save_state()

            try:
                # Execution
                self._git(["checkout", tgt.name])
                self._git(["merge", src.name, "--no-ff", "-m", f"Merge {src.name}"])

                # Update tags in state
                step.tags_created = list(self._get_tags() - pre_tags)
                self._save_state()

                # Run eDSL hooks
                for hook in tgt.hooks:
                    hook({"step": step, "source": src.name})

            except Exception as e:
                print(f"Error during merge to {tgt.name}: {e}")
                sys.exit(1)

        print("\nPipeline Complete.")
        # if os.path.exists(self.STATE_FILE): os.remove(self.STATE_FILE)

    def unwind(self):
        if not os.path.exists(self.STATE_FILE):
            print("Nothing to unwind.")
            return

        with open(self.STATE_FILE, "r") as f:
            data = json.load(f)
            steps = [MergeStep(**d) for d in data]

        for step in reversed(steps):
            print(f"Rolling back {step.target_branch}...")
            for tag in step.tags_created:
                self._git(["tag", "-d", tag])
            self._git(["checkout", step.target_branch])
            self._git(["reset", "--hard", step.original_sha])

        os.remove(self.STATE_FILE)
        print("Unwind complete.")

    # Helpers
    def _git(self, cmd): return subprocess.run(["git"] + cmd, check=True, capture_output=True, text=True)
    def _get_sha(self, b): return self._git(["rev-parse", b]).stdout.strip()
    def _get_tags(self): return set(self._git(["tag"]).stdout.splitlines())

# --- User Script ---

def test():
    dev = Branch("dev")
    staging = Branch("staging")
    main = Branch("main")

    # The eDSL definition
    dev > staging > main

    staging.when_merged(lambda ctx: os.system("echo 'Bump staging version'"))
    main.when_merged(lambda ctx: os.system("echo 'Bump main version'"))
    return [dev, staging, main]

def load_from_config():
    try:
        pyproject = toml.load("./pyproject.toml")
        config = pyproject['glisse']
        order = config['order']
        branches = [Branch(b) for b in order]
        functools.reduce(lambda b, c: b > c, branches)
        for branch in branches:
            for hook in config[branch.name]["merged"]["hooks"]:
                branch.when_merged(lambda ctx: os.system(hook))
        return branches
    except KeyError as e:
        print(f"config missing key {e}")
    except FileNotFoundError as e:
        print(f"file not found {e}")


if __name__ == "__main__":
    branches = load_from_config()
    assert len(branches) >= 1, f"must have at least one branch"
    base = branches[0]
    runner = DSLRunner(base)
    if "--undo" in sys.argv:
        runner.unwind()
    else:
        runner.execute()
