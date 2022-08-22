use log::info;
mod xtigervnc;

fn main() {
    env_logger::init();
    info!("Main thread start");

    let vnc_handle = std::thread::spawn(move || {
        xtigervnc::launch_tiger_vnc();
        info!("Thread finished");
    });

    info!("Main thread finished");
}

