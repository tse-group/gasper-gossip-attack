AWS_S3_BUCKET = 'my-p2pgossippropagation-experiments-s3'
AWS_EC2_REGIONS = [
    "eu-north-1",
    "ap-south-1",
    "eu-west-2",
    "eu-west-1",
    "ap-northeast-2",
    "ap-northeast-1",
    "sa-east-1",
    "ca-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "eu-central-1",
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
]
AWS_EC2_INSTANCE_TYPE = "m6g.medium"
AWS_EC2_KEY_NAME = "my-aws-instance-key"
AWS_EC2_KEY_PATH = "/home/user/.ssh/my-aws-instance-key"
GOSSIP_PORT = 7000
CREATE_NODES_PER_REGION = 50



# AWS interface borrowed from: https://github.com/asonnino/hotstuff

from fabric import task
import boto3
from collections import defaultdict, OrderedDict
import codecs
import time
import copy
import random
import json


class InstanceManager:
    INSTANCE_NAME = 'my-p2pgossippropagation-experiments-node'
    SECURITY_GROUP_NAME = 'my-p2pgossippropagation-experiments'

    def __init__(self):
        self.clients = OrderedDict()
        for region in AWS_EC2_REGIONS:
            print("Connecting to:", region)
            self.clients[region] = boto3.client('ec2', region_name=region)

    def _get(self, state):
        # Possible states are: 'pending', 'running', 'shutting-down',
        # 'terminated', 'stopping', and 'stopped'.
        ids, ips = defaultdict(list), defaultdict(list)
        for region, client in self.clients.items():
            r = client.describe_instances(
                Filters=[
                    {
                        'Name': 'tag:Name',
                        'Values': [self.INSTANCE_NAME]
                    },
                    {
                        'Name': 'instance-state-name',
                        'Values': state
                    }
                ]
            )
            instances = [y for x in r['Reservations'] for y in x['Instances']]
            for x in instances:
                ids[region] += [x['InstanceId']]
                if 'PublicIpAddress' in x:
                    ips[region] += [x['PublicIpAddress']]
        return ids, ips

    def _wait(self, state):
        # Possible states are: 'pending', 'running', 'shutting-down',
        # 'terminated', 'stopping', and 'stopped'.
        while True:
            time.sleep(1)
            ids, _ = self._get(state)
            if sum(len(x) for x in ids.values()) == 0:
                break

    def _create_security_group(self, client):
        client.create_security_group(
            Description='My experiments with message propagation in libp2p Gossipsub networks',
            GroupName=self.SECURITY_GROUP_NAME,
        )

        client.authorize_security_group_ingress(
            GroupName=self.SECURITY_GROUP_NAME,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{
                        'CidrIp': '0.0.0.0/0',
                        'Description': 'Debug SSH access',
                    }],
                    'Ipv6Ranges': [{
                        'CidrIpv6': '::/0',
                        'Description': 'Debug SSH access',
                    }],
                },
                {
                    'IpProtocol': 'tcp',
                    'FromPort': GOSSIP_PORT,
                    'ToPort': GOSSIP_PORT + 5000,
                    'IpRanges': [{
                        'CidrIp': '0.0.0.0/0',
                        'Description': 'Ports for gossip communication of nodes (libp2p: gossipsub)',
                    }],
                    'Ipv6Ranges': [{
                        'CidrIpv6': '::/0',
                        'Description': 'Ports for gossip communication of nodes (libp2p: gossipsub)',
                    }],
                },
            ]
        )

    def _get_ami(self, client):
        # The AMI changes with regions.
        response = client.describe_images(
            Filters=[{
                'Name': 'description',
                'Values': ['Canonical, Ubuntu, 20.04 LTS, arm64 focal image build on 2020-10-26']
            }]
        )
        return response['Images'][0]['ImageId']

    def create_instances(self, instances):
        assert isinstance(instances, int) and instances > 0

        # Create the security group in every region.
        for client in self.clients.values():
            print("Creating security group in:", client)
            self._create_security_group(client)

        # Create all instances.
        size = instances * len(self.clients)
        for client in self.clients.values():
            print('Creating instances in:', client)
            client.run_instances(
                ImageId=self._get_ami(client),
                InstanceType=AWS_EC2_INSTANCE_TYPE,
                KeyName=AWS_EC2_KEY_NAME,
                MaxCount=instances,
                MinCount=instances,
                SecurityGroups=[self.SECURITY_GROUP_NAME],
                TagSpecifications=[{
                    'ResourceType': 'instance',
                    'Tags': [{
                        'Key': 'Name',
                        'Value': self.INSTANCE_NAME
                    }]
                }],
                EbsOptimized=True,
                BlockDeviceMappings=[{
                    'DeviceName': '/dev/sda1',
                    'Ebs': {
                        'VolumeType': 'gp2',
                        'VolumeSize': 10,
                        'DeleteOnTermination': True
                    }
                }],
                IamInstanceProfile={
                    'Name': 'FullAccessToS3BucketsForEc2Instances'
                },
                # UserData=codecs.encode(open('startup.sh', 'r').read().encode(), 'base64'),
                UserData=open('startup-root.sh', 'r').read(),
            )

        # Wait for the instances to boot.
        print('Waiting for all instances to boot...')
        self._wait(['pending'])
        print(f'Successfully created {size} new instances')

    def terminate_instances(self):
        ids, _ = self._get(['pending', 'running', 'stopping', 'stopped'])
        size = sum(len(x) for x in ids.values())
        if size == 0:
            print(f'All instances are shut down')
            return

        # Terminate instances.
        for region, client in self.clients.items():
            if ids[region]:
                client.terminate_instances(InstanceIds=ids[region])

        # Wait for all instances to properly shut down.
        print('Waiting for all instances to shut down...')
        self._wait(['shutting-down'])
        for client in self.clients.values():
            client.delete_security_group(
                GroupName=self.SECURITY_GROUP_NAME
            )

        print(f'Testbed of {size} instances destroyed')

    def start_instances(self):
        ids, _ = self._get(['stopping', 'stopped'])
        for region, client in self.clients.items():
            if ids[region]:
                client.start_instances(InstanceIds=ids[region])
        size = sum(len(x) for x in ids.values())
        print(f'Starting {size} instances')

    def stop_instances(self):
        ids, _ = self._get(['pending', 'running'])
        for region, client in self.clients.items():
            if ids[region]:
                client.stop_instances(InstanceIds=ids[region])
        size = sum(len(x) for x in ids.values())
        print(f'Stopping {size} instances')

    def hosts(self, flat=False):
        _, ips = self._get(['pending', 'running'])
        return [x for y in ips.values() for x in y] if flat else ips

    def hosts_with_ids(self, flat=False):
        ids, ips = self._get(['pending', 'running'])
        ips = [x for y in ips.values() for x in y] if flat else ips
        ids = [x for y in ids.values() for x in y] if flat else ids
        return (ids, ips)

    def print_info(self):
        (ids, hosts) = self.hosts_with_ids()
        key = AWS_EC2_KEY_PATH
        text = ''
        for region, ips in hosts.items():
            text += f'\n Region: {region.upper()}\n'
            for i, ip in enumerate(ips):
                new_line = '\n' if (i+1) % 6 == 0 else ''
                text += f'{new_line} {i}\t{ids[region][i]}\tssh -i {key} -o "StrictHostKeyChecking no" ubuntu@{ip}\n'
        print(
            '\n'
            '----------------------------------------------------------------\n'
            ' INFO:\n'
            '----------------------------------------------------------------\n'
            f' Available machines: {sum(len(x) for x in hosts.values())}\n'
            f'{text}'
            '----------------------------------------------------------------\n'
        )


@task
def create(ctx, nodes=CREATE_NODES_PER_REGION):   # <--- nodes = number of nodes PER REGION!
    ''' Create a testbed'''
    InstanceManager().create_instances(nodes)

@task
def destroy(ctx):
    ''' Destroy the testbed '''
    InstanceManager().terminate_instances()

@task
def start(ctx):
    ''' Start all machines '''
    InstanceManager().start_instances()

@task
def stop(ctx):
    ''' Stop all machines '''
    InstanceManager().stop_instances()

@task
def info(ctx):
    ''' Display connect information about all the available machines '''
    InstanceManager().print_info()

@task
def zipcode(ctx):
    ctx.run('cd .. && zip -r code.zip Cargo.toml experiment gossip')
    ctx.run('mv ../code.zip .')

@task
def uploadcode(ctx):
    ctx.run(f'../venv/bin/aws s3 cp code.zip s3://{AWS_S3_BUCKET}/')
    ctx.run(f'../venv/bin/aws s3 cp startup-root.sh s3://{AWS_S3_BUCKET}/')
    ctx.run(f'../venv/bin/aws s3 cp startup-ubuntu.sh s3://{AWS_S3_BUCKET}/')

@task
def deploy(ctx):
    ctx.run(f'../venv/bin/aws s3 rm s3://{AWS_S3_BUCKET}/config.json')
    ctx.run(f'../venv/bin/aws s3 rm --recursive s3://{AWS_S3_BUCKET}/ready/')
    zipcode(ctx)
    uploadcode(ctx)

@task
def check(ctx):
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s1_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s2_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s3_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s4_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s5_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s6_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s7_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s8_ | wc -l')
    ctx.run(f'../venv/bin/aws s3 ls s3://{AWS_S3_BUCKET}/ready/ | grep s9_ | wc -l')

@task
def generateconfig(ctx):
    im = InstanceManager()
    ids, ips = im._get(['pending', 'running'])
    ips = [x for y in ips.values() for x in y]
    ids = [x for y in ids.values() for x in y]

    config = {
        'gossip': {
            'nodes': {}
        }
    }

    for (i, (id, ip)) in enumerate(zip(ids, ips)):
        lst = copy.copy(ids)
        lst.remove(id)
        random.shuffle(lst)
        node = {
            'name': id,
            'address': f"/ip4/{ip}/tcp/{GOSSIP_PORT+i}",
            # 'connect_to': lst[:random.randrange(5, 16)],
            'connect_to': lst[:10],
        }
        config['gossip']['nodes'][id] = node

    json.dump(config, open('config.json', 'w'), indent=4)

    print(ids, ips)
    print(config)
    ctx.run(f'md5sum config.json')

@task
def uploadconfig(ctx):
    ctx.run(f'cp config.json config_`md5sum config.json | awk \'{{ print $1; }}\'`.json')
    ctx.run(f'../venv/bin/aws s3 cp config.json s3://{AWS_S3_BUCKET}/')
    ctx.run(f'../venv/bin/aws s3 cp config_`md5sum config.json | awk \'{{ print $1; }}\'`.json s3://{AWS_S3_BUCKET}/')

@task
def downloadlogs(ctx):
    ctx.run(f'mkdir -p logs_`md5sum config.json | awk \'{{ print $1; }}\'`')
    ctx.run(f'../venv/bin/aws s3 cp --recursive s3://{AWS_S3_BUCKET}/logs_`md5sum config.json | awk \'{{ print $1; }}\'` logs_`md5sum config.json | awk \'{{ print $1; }}\'`/')
