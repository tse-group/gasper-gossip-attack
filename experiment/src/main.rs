mod config;
mod experiment;


use crate::experiment::Experiment;

use clap::{crate_name, crate_version, App, AppSettings, SubCommand};
use env_logger::Env;
use log::error;


#[tokio::main]
async fn main() {
    let matches = App::new(crate_name!())
        .version(crate_version!())
        .about("Experiments with information propagation in libp2p Gossipsub networks.")
        .args_from_usage("-v... 'Sets the level of verbosity'")
        .subcommand(
            SubCommand::with_name("run")
                .about("Runs a single node")
                .args_from_usage("<FILE> 'Config file'")
                .args_from_usage("<NAME> 'Node identity'")
        )
        .setting(AppSettings::SubcommandRequiredElseHelp)
        .get_matches();

    let log_level = match matches.occurrences_of("v") {
        0 => "error",
        1 => "warn",
        2 => "info",
        3 => "debug",
        _ => "trace",
    };

    let mut logger = env_logger::Builder::from_env(Env::default().default_filter_or(log_level));
    logger.format_timestamp_millis();
    logger.init();
    
    match matches.subcommand() {
        ("run", Some(subm)) => {
            let config_file = subm.value_of("FILE").unwrap();
            let name = subm.value_of("NAME").unwrap();
            match Experiment::run(config_file, name).await {
                Ok(_) => (),
                Err(e) => error!("{}", e),
            }
        }
        _ => unreachable!(),
    }
}
