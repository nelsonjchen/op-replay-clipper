use std::{thread, process};

use log::{info, error};
mod xtigervnc;

fn main() {
    env_logger::init();
    info!("Main thread start");

    // Luanch XTigerVNC in a separate thread
    let _handle = thread::spawn(|| {
        let mut child = xtigervnc::launch_tiger_vnc();
        let status = child.0.wait().expect("failed to wait for child process");
        error!("Child process exited with status, aborting whole process: {}", status);
        process::exit(1);
    });

    thread::sleep(std::time::Duration::from_secs(30));
    // If this thread exits, the whole program exits
    info!("Main thread finished");
}

