use std::{process::{Command, Stdio}, io::{BufReader, BufRead}};
use log::info;

pub(crate) fn launch_tiger_vnc() {
    info!("Launching XTigerVNC");
    // sudo Xtigervnc :0 -geometry 1920x1080 -SecurityTypes None
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

    child.wait().expect("failed to wait on child");
}
