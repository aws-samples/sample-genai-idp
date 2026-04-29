#!/usr/bin/env bash

usage() {
  echo "Usage: $0 <STACK_NAME> [--debug] [-h]" 1>&2
  echo "  STACK_NAME: IdP CloudFormation stack name" 1>&2
  echo "  --debug: Enable debug mode" 1>&2
  echo "  -h: Show this help" 1>&2
  echo "" 1>&2
  echo "Examples:" 1>&2
  echo "  $0 my-idp-stack" 1>&2
  echo "  $0 my-idp-stack --debug" 1>&2
  exit 1
}

DEBUG=

while getopts ":hv-:" o; do
  case "${o}" in
    -)
      case "${OPTARG}" in
        debug)
          DEBUG=true
          ;;
        *)
          if [ "$OPTERR" = 1 ] && [ "${optspec:0:1}" != ":" ]; then
              echo "Unknown option --${OPTARG}" >&2
          fi
          ;;
      esac
      ;;
    h)
      usage
      ;;
  esac
done

shift $((OPTIND-1))

# Get stack name from remaining arguments
if [ $# -eq 0 ]; then
  echo "Error: STACK_NAME is required"
  usage
fi

STACK_NAME="$1"

if [ ! -n "$STACK_NAME" ]; then
  echo "Error: STACK_NAME cannot be empty"
  usage
fi

if ! [[ $STACK_NAME =~ ^[A-Za-z0-9-]+$ ]] ; then
  echo "Error: Stack name should be alphanumeric characters or dashes only"
  exit 1
fi

function addhost() {
  HOSTNAME=$1
  IP=$2
  HOSTS_LINE="$IP $HOSTNAME"
  if [ -n "$(grep $IP /etc/hosts)" ]
    then
      echo "$IP Found in your /etc/hosts, Removing now..."
      sudo sed -i".bak" "/$1/d" /etc/hosts
  fi
  echo "Adding $HOSTNAME to your /etc/hosts"
  sudo -- sh -c -e "echo '$HOSTS_LINE' >> /etc/hosts"
  if [[ $OSTYPE == 'darwin'* ]]; then
    sudo ifconfig lo0 alias $IP up
  fi
}

function cleanhosts() {
  echo ""

  echo "Removing entries from host file to clean up..."
  if [[ $OSTYPE == 'darwin'* ]]; then
    sudo sed -i.bu "/127.0.0.10/d" /etc/hosts
  else
    echo sudo sed -i "/127.0.0.10/d" /etc/hosts
    sudo sed -i "/127.0.0.10/d" /etc/hosts
  fi
  echo "Done - bastion connection closed."
}

trap "cleanhosts" SIGINT SIGTERM

BASTION_NAME="${STACK_NAME}BastionHost"

BASTION_ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$BASTION_NAME Name=instance-state-name,Values=running --query "Reservations[*].Instances[*].InstanceId" --output text --no-cli-pager)
BASTION_AZ=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$BASTION_NAME Name=instance-state-name,Values=running --query "Reservations[*].Instances[*].Placement.AvailabilityZone" --output text --no-cli-pager)
VPC_ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$BASTION_NAME Name=instance-state-name,Values=running --query "Reservations[*].Instances[*].VpcId" --output text --no-cli-pager)

if [ ! -n "$BASTION_ID" ]; then
  echo "Unable to connect - Bastion not found for CloudFormation stack $STACK_NAME"
  exit 1
fi

### API Gateway
API_GW_ENDPOINT=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Outputs[?OutputKey=='ApiGatewayEndpoint'].OutputValue" --output text --no-cli-pager)
API_DOMAIN=$(echo $API_GW_ENDPOINT | sed 's|https://||' | sed 's|/.*||')

if [ ! -n "$API_GW_ENDPOINT" ]; then
  echo "Warning: Unable to retrieve ApiGatewayEndpoint from stack $STACK_NAME"
else
  # Get the VPC endpoint ID for API Gateway
  API_GW_VPCE_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query "Stacks[0].Parameters[?ParameterKey=='ApiGatewayVpcEndpointId'].ParameterValue" --output text --no-cli-pager)

  if [ -n "$API_GW_VPCE_ID" ]; then
    # Use VPC Endpoint DNS format: {vpce-id}.execute-api.{region}.amazonaws.com
    REGION=$(aws configure get region)
    API_GW_ID=$(echo $API_DOMAIN | cut -d'.' -f1)
    API_VPCE_DOMAIN="${API_GW_ID}-${API_GW_VPCE_ID}.execute-api.${REGION}.amazonaws.com"
    echo "Using API Gateway VPC Endpoint: $API_VPCE_DOMAIN"
  else
    echo "Warning: No VPC Endpoint ID found for API Gateway, using regular domain only"
    API_VPCE_DOMAIN=$API_DOMAIN
  fi
fi

# set /etc/hosts - map the API domains to localhost
addhost $API_DOMAIN 127.0.0.101
addhost $API_VPCE_DOMAIN 127.0.0.102

# create a random key to access the jumpbox instance
BASTION_FN=$(mktemp -t bastion.XXX -u)
ssh-keygen -t rsa -f $BASTION_FN -N ''
chmod 0600 $BASTION_FN
# valid for 60 seconds
aws ec2-instance-connect send-ssh-public-key --instance-id $BASTION_ID --availability-zone $BASTION_AZ --instance-os-user ec2-user --ssh-public-key file://$BASTION_FN.pub --output text --no-cli-pager

echo
echo "Forwarding API Gateway: https://${API_DOMAIN}/"
if [ -n "$API_VPCE_DOMAIN" ] && [ "$API_VPCE_DOMAIN" != "$API_DOMAIN" ]; then
  echo "  -> Tunneling through VPC Endpoint: $API_VPCE_DOMAIN"
fi
echo

echo "Connecting to bastion host with EC2 id: ${BASTION_ID}"
echo
echo "To terminate SSH tunnel, press ctrl + c"

sshcmd="ssh"
if [[ -x "$(which autossh 2>/dev/null)" ]]
then
  sshcmd="autossh -M 0"
fi

if [ $DEBUG ]; then
  interactive=""
else
  interactive="-N -vvv"
fi

# Build the SSH command
tunnel_command=(
    sudo -E $sshcmd
    -o ExitOnForwardFailure=yes
    -o "ProxyCommand=sh -c \"aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'\""
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=2
    -i "$BASTION_FN"
    "ec2-user@$BASTION_ID"
    -L "127.0.0.101:443:$API_DOMAIN:443"
    -L "127.0.0.102:443:$API_VPCE_DOMAIN:443"
    $interactive
)

echo 'tunnel command:'
echo "${tunnel_command[@]}"

"${tunnel_command[@]}"

cleanhosts
