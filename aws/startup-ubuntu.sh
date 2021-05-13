#! /bin/bash -ve

AWS_S3_BUCKET=my-p2pgossippropagation-experiments-s3

MY_AMI_LAUNCH_INDEX=`curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/ami-launch-index`
MY_INSTANCE_ID=`curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/instance-id`

cd
touch /home/ubuntu/empty-file-as-flag

aws s3 cp /home/ubuntu/empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s4_${MY_INSTANCE_ID}


curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source $HOME/.cargo/env
rustup default stable

aws s3 cp /home/ubuntu/empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s5_${MY_INSTANCE_ID}


mkdir -p experiment
aws s3 cp s3://${AWS_S3_BUCKET}/code.zip experiment/
aws s3 cp s3://${AWS_S3_BUCKET}/code-precompile-cache.zip experiment/
cd experiment/
unzip code.zip
unzip code-precompile-cache.zip
cargo build --release

aws s3 cp /home/ubuntu/empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s6_${MY_INSTANCE_ID}


while [ ! -f "config.json" ]; do
    sleep 1
    aws s3 cp s3://${AWS_S3_BUCKET}/config.json . || true
done

aws s3 cp /home/ubuntu/empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s7_${MY_INSTANCE_ID}


./target/release/experiment -vv run config.json ${MY_INSTANCE_ID} |& tee ${MY_INSTANCE_ID}.log

aws s3 cp /home/ubuntu/empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s8_${MY_INSTANCE_ID}


CONFIG_MD5=`md5sum config.json | awk '{ print $1; }'`
xz ${MY_INSTANCE_ID}.log
aws s3 cp ${MY_INSTANCE_ID}.log.xz s3://${AWS_S3_BUCKET}/logs_${CONFIG_MD5}/

aws s3 cp /home/ubuntu/empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s9_${MY_INSTANCE_ID}


sudo shutdown -h now
