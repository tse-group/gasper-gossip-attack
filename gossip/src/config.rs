use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use libp2p::{Multiaddr};


#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GossipNode {
    pub name: String,
    pub address: Multiaddr,
    pub connect_to: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GossipSwarm {
    pub nodes: HashMap<String, GossipNode>,
}

impl GossipSwarm {
    pub fn new(info: Vec<(String, Multiaddr, Vec<String>)>) -> Self {
        Self {
            nodes: info
                .into_iter()
                .map(|(name, address, connect_to)| {
                    let authority = GossipNode {
                        name: name.clone(),
                        address,
                        connect_to,
                    };
                    (name.clone(), authority)
                })
                .collect(),
        }
    }
}
