use std::collections::HashSet;
use std::fs::{File, remove_file};
use std::io::{Write, BufReader};
use std::process::{Command, exit};
use serde::{Serialize, Deserialize};
use serde_json;

// --- eDSL Core ---

type Hook = Box<dyn Fn(&MergeContext)>;

#[derive(Clone)]
struct Branch {
    name: String,
    hooks: Vec<Hook>,
    next_branch: Option<Box<Branch>>,
}

impl Branch {
    fn new(name: &str) -> Self {
        Branch {
            name: name.to_string(),
            hooks: Vec::new(),
            next_branch: None,
        }
    }

    fn when_merged<F>(&mut self, func: F) -> &mut Self
    where
        F: Fn(&MergeContext) + 'static,
    {
        self.hooks.push(Box::new(func));
        self
    }

    fn then(mut self, next: Branch) -> Branch {
        self.next_branch = Some(Box::new(next));
        *self.next_branch.as_mut().unwrap()
    }
}

// --- State Persistence ---

#[derive(Serialize, Deserialize)]
struct MergeStep {
    target_branch: String,
    original_sha: String,
    tags_created: Vec<String>,
}

struct MergeContext<'a> {
    step: &'a MergeStep,
    source: &'a str,
}

struct DSLRunner {
    start_node: Branch,
    history: Vec<MergeStep>,
}

impl DSLRunner {
    const STATE_FILE: &'static str = ".merge_state.json";

    fn new(start_node: Branch) -> Self {
        DSLRunner {
            start_node,
            history: Vec::new(),
        }
    }

    fn get_pipeline(&self) -> Vec<&Branch> {
        let mut pipeline = Vec::new();
        let mut current = Some(&self.start_node);

        while let Some(branch) = current {
            pipeline.push(branch);
            current = branch.next_branch.as_deref();
        }

        pipeline
    }

    fn save_state(&self) {
        let json = serde_json::to_string_pretty(&self.history).unwrap();
        let mut file = File::create(Self::STATE_FILE).unwrap();
        file.write_all(json.as_bytes()).unwrap();
    }

    fn execute(&mut self) {
        let pipeline = self.get_pipeline();

        for i in 0..pipeline.len() - 1 {
            let src = pipeline[i];
            let tgt = pipeline[i+1];

            println!("\n>>> Merging {} -> {}", src.name, tgt.name);

            let pre_tags = self.get_tags();
            let target_sha = self.get_sha(&tgt.name);

            let mut step = MergeStep {
                target_branch: tgt.name.clone(),
                original_sha: target_sha,
                tags_created: Vec::new(),
            };

            self.history.push(step.clone());
            self.save_state();

            // Merge
            if let Err(e) = self.git(&["checkout", &tgt.name]) {
                eprintln!("Error: {}", e);
                exit(1);
            }
            if let Err(e) = self.git(&["merge", &src.name, "--no-ff", "-m", &format!("Merge {}", src.name)]) {
                eprintln!("Error: {}", e);
                exit(1);
            }

            let post_tags = self.get_tags();
            step.tags_created = post_tags.difference(&pre_tags).cloned().collect();
            self.history.last_mut().unwrap().tags_created = step.tags_created.clone();
            self.save_state();

            // Run hooks
            for hook in &tgt.hooks {
                let ctx = MergeContext { step: &step, source: &src.name };
                hook(&ctx);
            }
        }

        println!("\nPipeline Complete.");
    }

    fn unwind(&self) {
        if !std::path::Path::new(Self::STATE_FILE).exists() {
            println!("Nothing to unwind.");
            return;
        }

        let file = File::open(Self::STATE_FILE).unwrap();
        let reader = BufReader::new(file);
        let steps: Vec<MergeStep> = serde_json::from_reader(reader).unwrap();

        for step in steps.iter().rev() {
            println!("Rolling back {}...", step.target_branch);
            for tag in &step.tags_created {
                let _ = self.git(&["tag", "-d", tag]);
            }
            let _ = self.git(&["checkout", &step.target_branch]);
            let _ = self.git(&["reset", "--hard", &step.original_sha]);
        }

        let _ = remove_file(Self::STATE_FILE);
        println!("Unwind complete.");
    }

    fn git(&self, args: &[&str]) -> Result<(), String> {
        let output = Command::new("git")
            .args(args)
            .output()
            .map_err(|e| e.to_string())?;

        if !output.status.success() {
            Err(String::from_utf8_lossy(&output.stderr).to_string())
        } else {
            Ok(())
        }
    }

    fn get_sha(&self, branch: &str) -> String {
        let output = Command::new("git")
            .args(&["rev-parse", branch])
            .output()
            .unwrap();
        String::from_utf8_lossy(&output.stdout).trim().to_string()
    }

    fn get_tags(&self) -> HashSet<String> {
        let output = Command::new("git")
            .args(&["tag"])
            .output()
            .unwrap();
        output.stdout.lines()
            .map(|l| l.unwrap().to_string())
            .collect()
    }
}

// --- User Script ---

fn main() {
    let mut dev = Branch::new("dev");
    let mut staging = Branch::new("staging");
    let mut main = Branch::new("main");

    dev.next_branch = Some(Box::new(staging.clone()));
    staging.next_branch = Some(Box::new(main.clone()));

    staging.when_merged(|_ctx| {
        let _ = Command::new("sh")
            .arg("-c")
            .arg("echo 'Bump staging version'")
            .status();
    });

    main.when_merged(|_ctx| {
        let _ = Command::new("sh")
            .arg("-c")
            .arg("echo 'Bump main version'")
            .status();
    });

    let mut runner = DSLRunner::new(dev);

    let args: Vec<String> = std::env::args().collect();
    if args.contains(&"--undo".to_string()) {
        runner.unwind();
    } else {
        runner.execute();
    }
}
