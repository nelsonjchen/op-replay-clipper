// OP Replay Clipper — Tauri Desktop App
//
// Manages the Docker compose lifecycle and opens the web UI in a native window.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

const SERVER_URL: &str = "http://localhost:7860";
const HEALTH_URL: &str = "http://localhost:7860/api/health";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);

struct AppState {
    docker_proc: Mutex<Option<Child>>,
    compose_dir: String,
}

/// Locate the op-replay-clipper repo directory.
fn find_compose_dir() -> String {
    if let Ok(dir) = env::var("CLIPPER_REPO_DIR") {
        if PathBuf::from(&dir).join("docker-compose.yml").exists() {
            return dir;
        }
    }

    let candidates = [
        dirs::home_dir().map(|h| h.join("op-replay-clipper")),
        dirs::home_dir().map(|h| h.join("Desktop/op-replay-clipper")),
        env::current_dir().ok().map(|c| c.join("../op-replay-clipper")),
    ];

    for candidate in candidates.into_iter().flatten() {
        if candidate.join("docker-compose.yml").exists() {
            return candidate.to_string_lossy().to_string();
        }
    }

    eprintln!("ERROR: Cannot find op-replay-clipper repo.");
    eprintln!("Set CLIPPER_REPO_DIR environment variable.");
    std::process::exit(1);
}

/// Start docker compose in the background.
fn start_docker(compose_dir: &str) -> Child {
    eprintln!("Starting Docker services from {}...", compose_dir);
    Command::new("docker")
        .args(["compose", "up", "web"])
        .current_dir(compose_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("Failed to start docker compose. Is Docker installed?")
}

/// Wait for the server health endpoint to respond.
fn wait_for_server() -> bool {
    eprintln!("Waiting for server...");
    let start = Instant::now();
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();

    while start.elapsed() < STARTUP_TIMEOUT {
        if let Ok(resp) = client.get(HEALTH_URL).send() {
            if resp.status().is_success() {
                eprintln!("Server ready!");
                return true;
            }
        }
        thread::sleep(Duration::from_secs(1));
    }
    eprintln!("Server did not start in time.");
    false
}

/// Stop docker compose.
fn stop_docker(compose_dir: &str, proc: &mut Option<Child>) {
    eprintln!("Stopping Docker services...");
    let _ = Command::new("docker")
        .args(["compose", "down"])
        .current_dir(compose_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    if let Some(mut child) = proc.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn main() {
    let compose_dir = find_compose_dir();
    let docker_proc = start_docker(&compose_dir);

    if !wait_for_server() {
        eprintln!("Failed to start server. Check Docker logs.");
        std::process::exit(1);
    }

    let state = AppState {
        docker_proc: Mutex::new(Some(docker_proc)),
        compose_dir: compose_dir.clone(),
    };

    tauri::Builder::default()
        .manage(state)
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<AppState>();
                let mut proc = state.docker_proc.lock().unwrap();
                stop_docker(&state.compose_dir, &mut proc);
            }
        })
        .setup(|app| {
            let window = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::External(SERVER_URL.parse().unwrap()),
            )
            .title("OP Replay Clipper")
            .inner_size(820.0, 920.0)
            .min_inner_size(600.0, 700.0)
            .build()?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Error running Tauri application");
}
