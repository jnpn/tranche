import subprocess
import json
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional

# --- Configuration & State Models ---

STATE_FILE = ".merge_state.json"

@dataclass
class MergeStep:
    target_branch: str
    original_sha: str
    tags_created: List[str] = field(default_factory=list)
    status: str = "PENDING"

@dataclass
class PipelineState:
    history: List[MergeStep] = field(default_factory=list)

# --- Git Utility Wrapper ---

class GitTool:
    @staticmethod
    def run(command: List[str]) -> str:
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"\n[!] Git Error: {e.stderr.strip()}")
            raise e

    @staticmethod
    def get_current_sha(branch: str) -> str:
        return GitTool.run(["git", "rev-parse", branch])

    @staticmethod
    def get_all_tags() -> set:
        tags = GitTool.run(["git", "tag"]).splitlines()
        return set(tags)

    @staticmethod
    def is_dirty() -> bool:
        return bool(GitTool.run(["git", "status", "--porcelain"]))

# --- Core Logic ---

class MergeManager:
    def __init__(self, branch_order: List[str], hooks: Dict[str, str]):
        self.branch_order = branch_order
        self.hooks = hooks
        self.state = self._load_state()

    def _load_state(self) -> PipelineState:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                history = [MergeStep(**step) for step in data.get("history", [])]
                return PipelineState(history=history)
        return PipelineState()

    def _save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    def merge_pipeline(self):
        """Sequential merge from branch_order[i] to branch_order[i+1]"""
        if GitTool.is_dirty():
            print("Aborting: Working directory has uncommitted changes.")
            return

        for i in range(len(self.branch_order) - 1):
            source = self.branch_order[i]
            target = self.branch_order[i + 1]

            print(f"\n>>> Transitioning: {source} -> {target}")

            # 1. Capture State Before Merge
            pre_tags = GitTool.get_all_tags()
            target_sha = GitTool.get_current_sha(target)

            step = MergeStep(target_branch=target, original_sha=target_sha)
            self.state.history.append(step)
            self._save_state()

            try:
                # 2. Perform Merge
                GitTool.run(["git", "checkout", target])
                GitTool.run(["git", "merge", source, "--no-ff", "-m", f"Automated merge from {source}"])

                # 3. Identify New Tags
                post_tags = GitTool.get_all_tags()
                step.tags_created = list(post_tags - pre_tags)

                # 4. Run Custom Hooks
                if target in self.hooks:
                    print(f"Running hook for {target}: {self.hooks[target]}")
                    subprocess.run(self.hooks[target], shell=True, check=True)

                step.status = "COMPLETED"
                self._save_state()

            except Exception as e:
                step.status = "FAILED"
                self._save_state()
                print(f"Pipeline halted at {target}. Fix manually or run --undo.")
                sys.exit(1)

        print("\nPipeline finished successfully. State cleared.")
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)

    def unwind(self):
        """Rollback in LIFO order"""
        if not self.state.history:
            print("No history found to undo.")
            return

        print("\n--- Starting Unwind (Rollback) ---")
        # Reverse the history for LIFO
        for step in reversed(self.state.history):
            print(f"Rolling back {step.target_branch}...")

            # Delete tags created during this step
            for tag in step.tags_created:
                try:
                    GitTool.run(["git", "tag", "-d", tag])
                    print(f"  - Deleted tag: {tag}")
                except:
                    print(f"  - Failed to delete tag {tag} (maybe already gone?)")

            # Hard reset branch to pre-merge SHA
            GitTool.run(["git", "checkout", step.target_branch])
            GitTool.run(["git", "reset", "--hard", step.original_sha])
            print(f"  - Reset {step.target_branch} to {step.original_sha}")

        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        print("\nUnwind complete. Repository restored.")

# --- Execution ---

if __name__ == "__main__":
    # Example Configuration
    MY_BRANCH_ORDER = ["dev", "staging", "master"]
    MY_HOOKS = {
        "staging": "echo 'Running staging tests...'",
        "master": "git tag -a v$(date +%Y%m%d) -m 'Production release'"
    }

    manager = MergeManager(MY_BRANCH_ORDER, MY_HOOKS)

    if len(sys.argv) > 1 and sys.argv[1] == "--undo":
        manager.unwind()
    else:
        manager.merge_pipeline()
