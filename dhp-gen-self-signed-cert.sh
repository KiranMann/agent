#!/bin/sh

# NOTE: This file was sourced from the DOT-Technology/DHP.BaseBuild GHE repository.
#       That file should be the source of truth.

# Self-signed SSL Certificate
#
# The CBA Cyber security team deem it mandatory to implement end-to-end encryption.
# For DHP this means that we need to use:
#
# 1. An SSL Certificate to encrypt traffic between clients (e.g. A user's web browser) and the ALB and
# 2. An SSL Certificate to encrypt traffic between the ALB and your application (e.g. Your API)
#
# What follows concerns itself with Point 2 above.
#
# Get the instance's hostname
# NOTE: The '-f' flag works on both Debian/Ubuntu and Alpine images. Alpine doesn't like '--fqdn'.
instance_fqdn=$(hostname -f)

echo "> Generating a new self-signed certificate (of type SSLServerAuthentication) for: ${instance_fqdn}"
echo ""

# Create the directories we need (in case they don't exist)
echo "   > Creating the required directories:"
echo "     - /etc/ssl/certs/"
echo "     - /etc/ssl/private/"
echo ""
mkdir -p /etc/ssl/certs/ /etc/ssl/private/

# Create a self-signed certificate for this specific EC2 instance.
# Every time an EC2 instance is provisioned, a new cert will be generated.
#
# NOTE: The '-nodes' flag means that we don't encrypt the private key i.e. no password is required.
#
# The key/cert can be retrieved later from the following locations:
#   - /etc/ssl/private/dhp-self-signed-cert-for-instance.key
#   - /etc/ssl/certs/dhp-self-signed-cert-for-instance.crt
echo "   > Using openssl to generate the self-signed certificate"
echo ""
openssl req -x509 -nodes \
    -keyout /etc/ssl/private/dhp-self-signed-cert-for-instance.key \
    -out /etc/ssl/certs/dhp-self-signed-cert-for-instance.crt \
    -subj "/CN=${instance_fqdn}" \
    -sha256 \
    -newkey rsa:2048 \
    -days 365

update-ca-certificates
# Lock down the file permissions
echo ""
echo "   > Locking down file permissions for:"
echo "     - /etc/ssl/certs/dhp-self-signed-cert-for-instance.crt"
echo "     - /etc/ssl/private/dhp-self-signed-cert-for-instance.key"
cat /etc/ssl/private/dhp-self-signed-cert-for-instance.key /etc/ssl/certs/dhp-self-signed-cert-for-instance.crt > /etc/ssl/certs/dhp-self-signed-cert-for-instance.pem
chmod 644 /etc/ssl/certs/dhp-self-signed-cert-for-instance.crt
chmod 640 /etc/ssl/private/dhp-self-signed-cert-for-instance.key
chmod 640 /etc/ssl/certs/dhp-self-signed-cert-for-instance.pem


echo ""
echo "> DONE!"
echo ""
