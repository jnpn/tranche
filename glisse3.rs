use std::cell::RefCell;
use std::collections::HashSet;
use std::fs::{File, remove_file, OpenOptions};
use std::io::{Write, BufRead, BufReader};
use std::process::{Command, exit};
use std::rc::Rc;

// --- eDSL Core ---

type Hook = Box<dyn Fn(&MergeContext)>;

struct Branch {
    name: String,
    hooks: Vec<Hook>,
    next_branch: Option<Rc<RefCell<Branch>>>,
}

impl Branch {
    fn new(name: &str) -> Rc<RefCell<Self>> {
        Rc::new(RefCell::new(Branch {
            name: name.to_string(),
            hooks: Vec::new(),
            next_branch: None,
        }))
    }

    fn when_merged<F>(&mut self, func: F)
    where
        F: Fn(&MergeContext) + 'static,
    {
        self.hooks.push(Box::new(func));
    }

    fn then(self_rc: &Rc<RefCell<Self>>, next: Rc<RefCell<Branch>>) {
        self_rc.borrow_mut().next_branch = Some(next);
    }
}

// --- State Persistence ---

#[derive(Clone)]
struct MergeStep {
    target_branch: String,
    original_sha: String,
    tags_created: Vec<String>,
}

struct MergeContext<'a> {
    step: &'a MergeStep,
    source: &'a str,
}

// --- DSL Runner ---

struct DSLRunner {
    start_node: Rc<RefCell<Branch>>,
    history: Vec<MergeStep>,
}

impl DSLRunner {
    const STATE_FILE: &'static str = ".merge_state.txt";

    fn new(start_node: Rc<RefCell<Branch>>) -> Self {
        DSLRunner {
            start_node,
            history: Vec::new(),
        }
    }

    fn get_pipeline(&self) -> Vec<Rc<RefCell<Branch>>> {
        let mut pipeline = Vec::new();
        let mut current = Some(self.start_node.clone());

        while let Some(branch_rc) = current {
            pipeline.push(branch_rc.clone());
            current = branch_rc.borrow().next_branch.clone();
        }

        pipeline
    }

    fn save_state(&self) {
        let mut file = File::create(Self::STATE_FILE).unwrap();
        for step in &self.history {
            let tags = step.tags_created.join(",");
            writeln!(file, "{} {} {}", step.target_branch, step.original_sha, tags).unwrap();
        }
    }

    fn load_state(&self) -> Vec<MergeStep> {
        if !std::path::Path::new(Self::STATE_FILE).exists() {
            return Vec::new();
        }

        let file = File::open(Self::STATE_FILE).unwrap();
        let reader = BufReader::new(file);
        let mut steps = Vec::new();

        for line in reader.lines() {
            let line = line.unwrap();
            let mut parts = line.splitn(3, ' ');
            let target_branch = parts.next().unwrap().to_string();
            let original_sha = parts.next().unwrap().to_string();
            let tags_created = parts.next().unwrap_or("").split(',').filter(|s| !s.is_empty()).map(|s| s.to_string()).collect();
            steps.push(MergeStep { target_branch, original_sha, tags_created });
        }

        steps
    }

    fn execute(&mut self) {
        let pipeline = self.get_pipeline();

        for i in 0..pipeline.len() - 1 {
            let src = pipeline[i].borrow();
            let tgt_rc = pipeline[i + 1].clone();
            let mut tgt = tgt_rc.borrow_mut();

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

            for hook in &tgt.hooks {
                let ctx = MergeContext { step: &step, source: &src.name };
                hook(&ctx);
            }
        }

        println!("\nPipeline Complete.");
    }

    fn unwind(&self) {
        let steps = self.load_state();
        if steps.is_empty() {
            println!("Nothing to unwind.");
            return;
        }

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
    let dev = Branch::new("dev");
    let staging = Branch::new("staging");
    let main = Branch::new("main");

    Branch::then(&dev, staging.clone());
    Branch::then(&staging, main.clone());

    staging.borrow_mut().when_merged(|_ctx| {
        let _ = Command::new("sh")
            .arg("-c")
            .arg("echo 'Bump staging version'")
            .status();
    });

    main.borrow_mut().when_merged(|_ctx| {
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
