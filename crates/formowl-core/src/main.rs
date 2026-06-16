use std::env;
use std::io::{self, Read};

fn main() {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .expect("failed to read stdin");

    match env::args().nth(1).as_deref() {
        Some("hash") | None => {
            println!("{}", formowl_core::sha256_prefixed(&input));
        }
        Some("normalize-newlines") => {
            print!("{}", formowl_core::normalize_newlines(&input));
        }
        Some("diff") => {
            let marker = "\n---FORMOWL_AFTER---\n";
            let (before, after) = input
                .split_once(marker)
                .expect("diff input must contain a line with ---FORMOWL_AFTER---");
            print!("{}", formowl_core::unified_diff(before, after, "before", "after"));
        }
        Some(command) => {
            eprintln!("unknown formowl-core command: {command}");
            std::process::exit(2);
        }
    }
}
