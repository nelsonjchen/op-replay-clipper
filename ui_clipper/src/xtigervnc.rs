use log::{info, warn};
use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
};

pub struct ChildGuard(pub Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        // You can check std::thread::panicking() here
        match self.0.kill() {
            Err(e) => warn!("Could not kill child process: {}", e),
            Ok(_) => info!("Child process killed"),
        }
    }
}

pub(crate) fn launch_tiger_vnc() -> ChildGuard {
    info!("Launching XTigerVNC in the background");

    let mut child = Command::new("sudo")
        .arg("Xtigervnc")
        .arg(":0")
        .arg("-geometry")
        .arg("1920x1080")
        .arg("-SecurityTypes")
        .arg("None")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to execute process");
    let stdout = child.stdout.take().unwrap();
    std::thread::spawn(move || {
        BufReader::new(stdout).lines().for_each(|line| {
            info!("{}", line.unwrap());
        });
    });

    let stderr = child.stderr.take().unwrap();
    std::thread::spawn(move || {
        BufReader::new(stderr).lines().for_each(|line| {
            info!("{}", line.unwrap());
        });
    });

    ChildGuard(child)
}
