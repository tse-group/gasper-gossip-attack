use crate::experiment::ExperimentError;

use gossip::GossipSwarm;

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use std::fs::{self};


pub trait Export: Serialize + DeserializeOwned {
    fn read(path: &str) -> Result<Self, ExperimentError> {
        let reader = || -> Result<Self, std::io::Error> {
            let data = fs::read(path)?;
            Ok(serde_json::from_slice(data.as_slice())?)
        };
        reader().map_err(|e| ExperimentError::ReadError {
            file: path.to_string(),
            message: e.to_string(),
        })
    }
}


#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct Config {
    pub gossip: GossipSwarm,
}

impl Export for Config {}
