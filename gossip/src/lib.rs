mod config;

pub use crate::config::GossipSwarm;

use libp2p::ping::{Ping, PingEvent, PingConfig};
use libp2p::gossipsub::{MessageId, GossipsubEvent, GossipsubMessage, IdentTopic as Topic, MessageAuthenticity, ValidationMode};
use libp2p::swarm::{SwarmBuilder};
use libp2p::{gossipsub, identity, PeerId, NetworkBehaviour};
use libp2p::core::multiaddr::{Protocol};

use tokio::time::{Duration};
use tokio::sync::{mpsc::channel as mpsc_channel, mpsc::Receiver as MpscReceiver, mpsc::Sender as MpscSender};

use ed25519_dalek::{Sha512, Digest as _};

use std::convert::{TryInto, From};
use std::collections::{HashMap};
use std::net::Ipv4Addr;
use log::{info, warn};
use thiserror::Error;


pub fn sha512_hash(data: &Vec<u8>) -> Vec<u8> {
    let mut hasher = Sha512::new();
    hasher.update(&data);
    hasher.finalize().as_slice()[..32].try_into().unwrap()
}


pub type GossipResult<T> = Result<T, GossipError>;

#[derive(Error, Debug)]
pub enum GossipError {
    #[error("IO error: {0}")]
    IOError(#[from] std::io::Error),

    #[error("Libp2p transport error")]
    TransportError(#[from] libp2p::TransportError<std::io::Error>),

    #[error("Libp2p gossipsub subscription error")]
    SubscriptionError(),
}

impl From<libp2p::gossipsub::error::SubscriptionError> for GossipError {
    fn from(_value: libp2p::gossipsub::error::SubscriptionError) -> GossipError {
        GossipError::SubscriptionError {}
    }
}


#[derive(Debug)]
enum MyOutEvent {
    Ping { e: PingEvent },
    Gossipsub { e: GossipsubEvent },
}

impl From<PingEvent> for MyOutEvent {
    fn from(value: PingEvent) -> MyOutEvent {
        MyOutEvent::Ping { e: value }
    }
}

impl From<GossipsubEvent> for MyOutEvent {
    fn from(value: GossipsubEvent) -> MyOutEvent {
        MyOutEvent::Gossipsub { e: value }
    }
}


// Custom network behavior
#[derive(NetworkBehaviour)]
#[behaviour(out_event = "MyOutEvent", event_process = false)]
struct MyBehaviour {
    ping: Ping,
    gossipsub: gossipsub::Gossipsub,
}


#[derive(Debug, Clone)]
pub enum GossipCmd {
    Subscribe(String, MpscSender<Vec<u8>>),
    Publish(String, Vec<u8>),
}


#[derive(Debug, Clone)]
pub struct Gossip(MpscSender<GossipCmd>);

impl Gossip {
    pub async fn run(
            name: String,
            swarm_config: GossipSwarm,
        ) -> Result<Gossip, GossipError> {

        // BASED ON rust-libp2p EXAMPLES: https://github.com/libp2p/rust-libp2p/tree/v0.36.0/examples


        // Create a random PeerId
        let local_key = identity::Keypair::generate_ed25519();
        let local_peer_id = PeerId::from(local_key.public());
        info!("Local gossip peer id: {:?}", local_peer_id);

        // Set up an encrypted TCP Transport over the Mplex and Yamux protocols
        let transport = libp2p::development_transport(local_key.clone()).await?;


        // Create a Swarm to manage peers and events
        let mut swarm = {
            // let mdns = Mdns::new(Default::default()).await?;
            let ping = Ping::new(
                PingConfig::new()
                .with_timeout(Duration::from_secs(5))
                .with_interval(Duration::from_secs(5))
                .with_max_failures(2u32.try_into().unwrap())
                .with_keep_alive(true)
            );

            // Set a custom gossipsub
            let gossipsub_config = gossipsub::GossipsubConfigBuilder::default()
                // .heartbeat_interval(Duration::from_secs(2))   // This is set to aid debugging by not cluttering the log space
                .validation_mode(ValidationMode::Strict)   // This sets the kind of message validation. The default is Strict (enforce message signing)
                .message_id_fn(|message: &GossipsubMessage| {   // To content-address message, we can take the hash of message and use it as an ID.
                    MessageId(sha512_hash(&message.data))
                })   // content-address messages. No two messages of the same content will be propagated.
                .max_transmit_size(2*16*65536)
                .build()
                .expect("Valid config");

            // build a gossipsub network behaviour
            let gossipsub: gossipsub::Gossipsub =
                gossipsub::Gossipsub::new(MessageAuthenticity::Signed(local_key), gossipsub_config)
                    .expect("Correct configuration");

            // putting it all together
            let behaviour = MyBehaviour {
                ping: ping,
                gossipsub: gossipsub,
            };

            // build the swarm
            SwarmBuilder::new(transport, behaviour, local_peer_id)
                // We want the connection background tasks to be spawned
                // onto the tokio runtime.
                .executor(Box::new(|fut| { tokio::spawn(fut); }))
                .build()
        };


        // retrieve my config
        let my_config = swarm_config.nodes.get(&name).expect("failed to retrieve swarm config info for myself!");

        // Listen on all interfaces and whatever port the OS assigns
        let listen_everywhere = my_config.address.replace(0, |_| { Some(Protocol::Ip4(Ipv4Addr::new(0, 0, 0, 0))) }).unwrap();
        info!("Listening on: {:?}", listen_everywhere);
        libp2p::Swarm::listen_on(&mut swarm, listen_everywhere)?;


        // Reach out to other nodes as specified in swarm config
        for connect_to_name in my_config.connect_to.iter() {
            let connect_to_peer_config = swarm_config.nodes.get(connect_to_name).expect("failed to retrieve swarm config info for connect_to!");
            match libp2p::Swarm::dial_addr(&mut swarm, connect_to_peer_config.address.clone()) {
                Ok(_) => info!("Dialed {:?}", connect_to_peer_config),
                Err(e) => info!("Dial {:?} failed: {:?}", connect_to_peer_config, e),
            }
        }


        // queues for the gossip unit (commands and outgoing messages)
        let (tx_cmds, mut rx_cmds) = mpsc_channel(1000);

        {
            let _tx_cmds = tx_cmds.clone();
            tokio::spawn(async move {
                info!("Gossip started!");

                let mut subscriptions = HashMap::<String, MpscSender<Vec<u8>>>::new();

                loop {
                    tokio::select! {
                        cmd = rx_cmds.recv() => {
                            // info!("GossipCmd: {:?}", cmd.clone());

                            match cmd {
                                Some(cmd) => match cmd {
                                    GossipCmd::Subscribe(topic, tx) => {
                                        subscriptions.insert(topic.clone(), tx);
                                        swarm.gossipsub.subscribe(&Topic::new(topic.clone())).expect("gossipsub subscribe failed!");
                                    },
                                    GossipCmd::Publish(topic, value) => {
                                        if let Err(publish_ret) = swarm.gossipsub.publish(Topic::new(topic.clone()), value.clone()) {
                                            warn!("Gossipsub publish failed: {:?}", publish_ret);
                                        }

                                        subscriptions.get(&topic).expect("topic not subscribed!")
                                            .send(value.clone()).await.expect("failed local replay!");
                                    },
                                },
                                None => {
                                    panic!("Stream of incoming gossip commands was closed, terminating ...");
                                }
                            }
                        },

                        ev = swarm.next() => {
                            // info!("Swarm next() returned: {:?}", ev);

                            match ev {
                                MyOutEvent::Ping { e: _event } => {
                                    // info!("PingEvent: {:?}", event);
                                },

                                MyOutEvent::Gossipsub { e: event } => {
                                    // info!("GossipsubEvent: {:?}", event);

                                    match event {
                                        GossipsubEvent::Message { message, .. } => {
                                            let value = message.data;
                                            subscriptions.get(&message.topic.into_string()).expect("topic not subscribed!")
                                                .send(value).await.expect("failed local delivery!");
                                        },
                                        _ => { },
                                    };
                                },
                            }
                        },
                    }
                }

                // info!("Gossip finished!");
            });
        }

        Ok(Self(tx_cmds))
    }

    pub async fn subscribe(&self, topic: String) -> (MpscReceiver<Vec<u8>>, MpscSender<Vec<u8>>) {
        let (tx_outbound_msgs, mut rx_outbound_msgs): (MpscSender<Vec<u8>>, MpscReceiver<Vec<u8>>) = mpsc_channel(1000);
        let (tx_inbound_msgs, rx_inbound_msgs) = mpsc_channel(1000);
        let tx_cmds = self.0.clone();

        tx_cmds.send(GossipCmd::Subscribe(topic.clone(), tx_inbound_msgs.clone())).await.expect("sending GossipCmd::Subscribe failed!");

        tokio::spawn(async move {
            loop {
                let msg = rx_outbound_msgs.recv().await;
                match msg {
                    Some(msg) => {
                        tx_cmds.send(GossipCmd::Publish(topic.clone(), msg)).await.expect("sending GossipCmd::Publish failed!");
                    },
                    None => {
                        panic!("Stream of outbound messages was closed, terminating ...");
                    }
                }
            }
        });

        (rx_inbound_msgs, tx_outbound_msgs.clone())
    }
}
