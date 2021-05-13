use crate::config::Export as _;
use crate::config::{Config};

use gossip::{Gossip, GossipError};

use log::{debug, info, warn, error};
use thiserror::Error;
use serde::{Deserialize, Serialize};
use tokio::time::{self, Duration};
use std::time::{SystemTime};
use std::convert::{TryFrom, TryInto};
use std::cmp::min;
use rand::prelude::*;
use rand::rngs::StdRng;


#[derive(Debug, Serialize, Deserialize, Default)]
pub struct Msg {
    pub origin: String,
    pub seqno: usize,
    pub timestamp: f64,
}

impl TryFrom<Vec<u8>> for Msg {
    type Error = Box<bincode::ErrorKind>;

    fn try_from(value: Vec<u8>) -> Result<Self, Self::Error> {
        bincode::deserialize::<Msg>(&value)
    }
}

impl TryFrom<&Msg> for Vec<u8> {
    type Error = Box<bincode::ErrorKind>;

    fn try_from(value: &Msg) -> Result<Self, Self::Error> {
        bincode::serialize(&value)
    }
}


fn get_random_seed(s: String) -> u64 {
    let s_vec = s.as_bytes().to_vec();
    let mut v: u64 = 0;
    for i in 0..min(8, s_vec.len()) {
        v = (v<<8) + (s_vec[i] as u64);
    }
    v
}


const GET_READY_DELAY_1_MS: u64 = 5_000;
const GET_READY_DELAY_2_MS: u64 = 5_000;
const SHUTDOWN_DELAY_MS: u64 = 15_000;
const RAND_DELAY_MIN: u32 = 0;
const RAND_DELAY_MAX: u32 = 5_000;
const RUNTIME_S: u64 = 20*60;
const NUM_SENDERS: usize = 5;


#[derive(Error, Debug)]
pub enum ExperimentError {
    #[error("Failed to read config file '{file}': {message}")]
    ReadError { file: String, message: String },

    #[error(transparent)]
    GossipError(#[from] GossipError),
}

pub struct Experiment {}


impl Experiment {
    pub async fn run(
        config_file: &str,
        my_name: &str,
    ) -> Result<(), ExperimentError> {

        // read config
        let config = Config::read(config_file)?;
        info!("Config: {:?}", config);
        let my_config = config.gossip.nodes.get(my_name).expect("Failed to read own config, maybe provided node name is wrong?");
        info!("Name: {} Config: {:?}", my_name, my_config);
        let num_nodes = config.gossip.nodes.len();

        // decide who is a sender and who not
        let mut nodes_sorted: Vec<_> = config.gossip.nodes.keys().cloned().collect();
        nodes_sorted.sort();
        let senders = &nodes_sorted[..NUM_SENDERS];
        info!("Senders: {:?}", senders);

        // setup gossip
        let gossip = Gossip::run(my_name.to_string(), config.gossip).await?;
        time::sleep(Duration::from_millis(GET_READY_DELAY_1_MS)).await;

        let (mut rx_inbound_msgs, tx_outbound_msgs) = gossip.subscribe("test-topic".to_string()).await;

        // receive gossip msgs
        {
            let my_name = my_name.to_string();
            tokio::spawn(async move {
                loop {
                    let msg: Msg = rx_inbound_msgs.recv()
                        .await
                        .expect("Failed to recv msg!")
                        .try_into()
                        .expect("Failed to deserialize msg!");
                    info!("Received by {} at {}: {:?}",
                        my_name,
                        SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).expect("Failed to obtain system time!?").as_secs_f64(),
                        msg);
                }
            });
        }

        tokio::time::sleep(tokio::time::Duration::from_millis(GET_READY_DELAY_2_MS)).await;

        let mut rng = StdRng::seed_from_u64(get_random_seed(my_name.to_string()));
        let time_start = SystemTime::now();

        if senders.contains(&my_name.to_string()) {
            let rand_delay_min = 0 as u32;
            let rand_delay_max = (2*senders.len() * 500) as u32; // avg total rate: 1 msg per 500ms

            // send gossip msgs
            let mut seqno = 0;
            loop {
                let random_delay = (rng.gen::<u32>() % (rand_delay_max - rand_delay_min)) + rand_delay_min;
                tokio::time::sleep(tokio::time::Duration::from_millis(random_delay as u64)).await;

                if let Ok(d) = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH) {
                    let msg = Msg { origin: my_name.to_string(), seqno, timestamp: d.as_secs_f64() };
                    tx_outbound_msgs.send((&msg).try_into().expect("Failed to serialize msg!"))
                        .await
                        .expect("Failed to send msg!");
                    info!("Sent by {} at {}: {:?}",
                        my_name,
                        SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).expect("Failed to obtain system time!?").as_secs_f64(),
                        msg);
                    seqno += 1;

                } else {
                    panic!("Failed to obtain system time!?");
                }

                if SystemTime::now().duration_since(time_start).expect("Failed to obtain system time!?").as_secs() > RUNTIME_S {
                    break;
                }
            }

        } else {
            tokio::time::sleep(tokio::time::Duration::from_secs(RUNTIME_S)).await;
        }

        info!("End of runtime reached, shutting down ...");
        tokio::time::sleep(tokio::time::Duration::from_millis(SHUTDOWN_DELAY_MS)).await;

        Ok(())
    }
}
