#! /bin/bash -ve

AWS_S3_BUCKET=my-p2pgossippropagation-experiments-s3

MY_AMI_LAUNCH_INDEX=`curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/ami-launch-index`
MY_INSTANCE_ID=`curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/instance-id`

sudo apt-get -y update
sudo apt-get -y install awscli
touch empty-file-as-flag

aws s3 cp empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s1_${MY_INSTANCE_ID}

sudo apt-get -y update
sudo apt-get -y autoremove

aws s3 cp empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s2_${MY_INSTANCE_ID}

sudo apt-get -y install build-essential cmake
sudo apt-get -y install net-tools ifstat vnstat zip unzip

aws s3 cp empty-file-as-flag s3://${AWS_S3_BUCKET}/ready/s3_${MY_INSTANCE_ID}

aws s3 cp s3://${AWS_S3_BUCKET}/startup-ubuntu.sh /home/ubuntu/startup-ubuntu.sh
chmod +x /home/ubuntu/startup-ubuntu.sh
chown ubuntu:ubuntu /home/ubuntu/startup-ubuntu.sh
su - -c "/home/ubuntu/startup-ubuntu.sh" ubuntu
