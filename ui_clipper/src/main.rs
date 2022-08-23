use std::{process, thread, time::Duration};

use log::{error, info};
use tmux_interface::TmuxCommand;
mod xtigervnc;

fn main() {
    env_logger::init();
    info!("Main thread start");

    // Luanch XTigerVNC in a separate thread
    let _handle = thread::spawn(|| {
        let mut child = xtigervnc::launch_tiger_vnc();
        let status = child.0.wait().expect("failed to wait for child process");
        error!(
            "Child process exited with status, aborting whole process: {}",
            status
        );
        process::exit(1);
    });

    let mut tmux = TmuxCommand::new();
    tmux.new_session()
        .detached()
        .session_name("repeat")
        .output()
        .unwrap();
    tmux.send_keys().key("sleep 300").key("C-m").output();
    thread::sleep(Duration::from_secs(300));

    // If this thread exits, the whole program exits
    info!("Main thread finished");
}
