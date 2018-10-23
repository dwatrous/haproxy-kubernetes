# haproxy-kubernetes
Scripts that make it possible to have HAProxy dynamically configure itself based on the current state of Services in a kubernetes cluster

# Background
I developed thsi script to provide a gateway into a kubernetes cluster deployed on OpenStack. If I had been in public cloud, I would probably have used a managed load balancer. When I deployed the kubernetes cluster, I deployed the gateway server(s) as a nodes, so they would have the same network overlay (e.g. flannel, calico, etc.) as the rest of the cluster. This meant that HAProxy could route traffic directly to container workloads.

# Setup gateway
A gateway server is used to allow incoming traffic into the kubernetes cluster based on services. The steps below setup an HAProxy server for this purpose.

  * Disable pod scheduling on the gateway node(s)
  * Create ServiceAccount for gateway API calls
  * Install HAProxy
  * Copy over gateway config script and setup cron
  * Some adjustment may be required to security groups (reference)

To run the `kubectl` commands below, first SSH into one of the master nodes through the bastion.

## Disable pod scheduling
The gateway is setup by kubespray as a node to facilitate pod access using the selected network overlay (e.g. calico). This first command disables pod scheduling so all resources are available to HAProxy.

```
kubectl cordon k8s-gateway-0
```

## Create ServiceAccount for gateway
The following commands _should be run on one of the master nodes_ (e.g. __k8s-master-0__) and will create a ServiceAccount, ClusterRole and a ClusterRoleBinding to tie them together. Even though the ServiceAccount has a namespace, ClusterRoles span all namespaces.

```
kubectl create serviceaccount gateway --namespace kube-system
kubectl create clusterrole gateway --verb=get,list,watch --resource=services,endpoints,nodes
kubectl create clusterrolebinding gateway --clusterrole=gateway --serviceaccount=kube-system:gateway
```

The commands below show details about the resources created above. The first two commands allow you to retrieve the TOKEN. The last command helps to verify that the TOKEN gives access to the expected resources. Obviously substitute the IP address for one of the master nodes in the cluster.

```
kubectl get sa gateway --namespace kube-system -o yaml
kubectl describe secret gateway-token-v3l6f --namespace kube-system
kubectl get clusterrole gateway -o yaml
kubectl get clusterrolebinding gateway -o yaml
kubectl auth can-i get nodes --server=https://k8s-master:6443 --insecure-skip-tls-verify --token TOKEN 
```

## Install HAProxy
Install HAProxy and python libraries using apt-get. The dynamic configuration of HAProxy requires jinja2, which is installed using pip below.

### Ubuntu or Debian

```
sudo apt-get update
sudo apt-get install -y haproxy python-setuptools
sudo easy_install pip
sudo pip install jinja2
```

### RHEL or CentOS

```
sudo yum install -y haproxy
sudo easy_install pip
sudo pip install jinja2
sudo mkdir /run/haproxy/
```

In some cases it can be necessary to validate haproxy. `haproxy -v` will print the current version of HAProxy installed. A configuration file can be validated using `haproxy -f /etc/haproxy/haproxy.cfg -c`. The HAProxy service can be managed using `sudo service haproxy start|stop|restart`.

## Create DNS A records

Create a single A record to resolve all traffic (wildcard) for the cluster. For example

```
A *.datacenter2.example.com 192.168.12.219
```

The IP above could be public, but it really just needs to be routable on the network that needs access to the workloads you run on kubernetes.

## Copy gateway config script and create cron job
Copy the following files from the `/eng_resources` directory

  * `gateway-config-cron`
    * `chmod +x gateway-config-cron`
  * `gateway-haproxy-config.py`
  * `haproxy.j2`

The last two files need to be in the same directory. The shell script `gateway-config-cron` needs to be updated with the correct path to `gateway-haproxy-config.py`.

The file `gateway-haproxy-config.py` needs to be updated with the IP address of one of the master nodes and the TOKEN for the ServiceAccount created above.

The file `haproxy.j2` needs to be updated based on the SSL certificate and domain name used in the next step.

`sudo crontab -e`

`* * * * * cd /home/centos && ./gateway-config-cron`

## Setup SSL automation
Kubernetes API interactions on port 7443 require SSL. This process uses [Let's Encrypt](https://letsencrypt.org/) to get a valid, signed certificate to provide SSL. This process also uses the [acme.sh script](https://github.com/Neilpang/acme.sh) to interact with Let's Encrypt.

The commands below will need to be adjusted to the cluster being configured. In the below example, the Austin Engineering cluster is assumed: `api.datacenter1.example.com`.

### Install acme.sh on the gateway

```
[root@k8s-gateway-0 ~]# curl https://get.acme.sh | sh
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100   705  100   705    0     0    853      0 --:--:-- --:--:-- --:--:--   853
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100  164k  100  164k    0     0   552k      0 --:--:-- --:--:-- --:--:--  554k
[Thu May  3 05:00:47 UTC 2018] Installing from online archive.
[Thu May  3 05:00:47 UTC 2018] Downloading https://github.com/Neilpang/acme.sh/archive/master.tar.gz
[Thu May  3 05:00:47 UTC 2018] Extracting master.tar.gz
[Thu May  3 05:00:47 UTC 2018] Installing to /root/.acme.sh
[Thu May  3 05:00:47 UTC 2018] Installed to /root/.acme.sh/acme.sh
[Thu May  3 05:00:48 UTC 2018] Installing alias to '/root/.bashrc'
[Thu May  3 05:00:48 UTC 2018] OK, Close and reopen your terminal to start using acme.sh
[Thu May  3 05:00:48 UTC 2018] Installing alias to '/root/.cshrc'
[Thu May  3 05:00:48 UTC 2018] Installing alias to '/root/.tcshrc'
[Thu May  3 05:00:48 UTC 2018] Installing cron job
[Thu May  3 05:00:48 UTC 2018] Good, bash is found, so change the shebang to use bash as preferred.
[Thu May  3 05:00:48 UTC 2018] OK
[Thu May  3 05:00:48 UTC 2018] Install success!
```

### Set environment variables and issue certificate
In this example I'm using NS1 for DNS, so I reference the `NS1_Key` value. acme.sh supports loads of other DNS options.

```
[root@k8s-gateway-0 ~]# export NS1_Key=REDACTED

[root@k8s-gateway-0 ~]# acme.sh --issue --dns dns_nsone -d api.datacenter1.example.com
[Thu May  3 06:15:09 UTC 2018] Creating domain key
[Thu May  3 06:15:09 UTC 2018] The domain key is here: /root/.acme.sh/api.datacenter1.example.com/api.datacenter1.example.com.key
[Thu May  3 06:15:09 UTC 2018] Single domain='api.datacenter1.example.com'
[Thu May  3 06:15:09 UTC 2018] Getting domain auth token for each domain
[Thu May  3 06:15:09 UTC 2018] Getting webroot for domain='api.datacenter1.example.com'
[Thu May  3 06:15:09 UTC 2018] Getting new-authz for domain='api.datacenter1.example.com'
[Thu May  3 06:15:10 UTC 2018] The new-authz request is ok.
[Thu May  3 06:15:10 UTC 2018] api.datacenter1.example.com is already verified, skip dns-01.
[Thu May  3 06:15:10 UTC 2018] Verify finished, start to sign.
[Thu May  3 06:15:11 UTC 2018] Cert success.
-----BEGIN CERTIFICATE-----
MIIGJTCCBQ2gAwIBAgISBDOBQhnPFhMUPaqTBDzCCVCAMA0GCSqGSIb3DQEBCwUA
MEoxCzAJBgNVBAYTAlVTMRYwFAYDVQQKEw1MZXQncyBFbmNyeXB0MSMwIQYDVQQD
ExpMZXQncyBFbmNyeXB0IEF1dGhvcml0eSBYMzAeFw0xODA1MDMwNTE1MTFaFw0x
ODA4MDEwNTE1MTFaMCgxJjAkBgNVBAMTHWFwaS5lbmcuYXVzdGluLnRyaW5ldC1r
OHMuY29tMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7BlzI03auW8P
PKcUxuxVF0iOeMy/cfIdR9XadyqvOrP4jbrQ+/RxzNvWQ9DA6ii1hR++exEzkHL5
FiNFXLZsByVrJS4DyaYuNmgKcmQWjwdax6oGispWnm77SrMX1Umy5wJfzVKG0rFX
sb2ywqQCWDs8ErwLCGhDjl7l6psazdWcrNllZXB8mn4VBVIL0nTr8uJfhjq2/h2x
dkHHsrzO67+v2+/2/6Dg2zFK840H7yUVkkzoeuf8KtOLf/gWNoH6bDhmdIv3g5In
4zQvuFYLETl+ojuba/wOfeRAtZX7YJh8QrKNEUKeZTAL9/GhjylhVuGvGeTZcRfu
sxFg/0zuqwIDAQABo4IDJTCCAyEwDgYDVR0PAQH/BAQDAgWgMB0GA1UdJQQWMBQG
aW5ldC1rOHMuY29tMIH+BgNVHSAEgfYwgfMwCAYGZ4EMAQIBMIHmBgsrBgEEAYLf
CCsGAQUFBwMBBggrBgEFBQcDAjAMBgNVHRMBAf8EAjAAMB0GA1UdDgQWBBQMKZfi
J2SdV53YXyV7WHdtjP57lTAfBgNVHSMEGDAWgBSoSmpjBH3duubRObemRWXv86js
My5sZXRzZW5jcnlwdC5vcmcwLwYIKwYBBQUHMAKGI2h0dHA6Ly9jZXJ0LmludC14
oTBvBggrBgEFBQcBAQRjMGEwLgYIKwYBBQUHMAGGImh0dHA6Ly9vY3NwLmludC14
My5sZXRzZW5jcnlwdC5vcmcvMCgGA1UdEQQhMB+CHWFwaS5lbmcuYXVzdGluLnRy
EwEBATCB1jAmBggrBgEFBQcCARYaaHR0cDovL2Nwcy5sZXRzZW5jcnlwdC5vcmcw
gasGCCsGAQUFBwICMIGeDIGbVGhpcyBDZXJ0aWZpY2F0ZSBtYXkgb25seSBiZSBy
ZWxpZWQgdXBvbiBieSBSZWx5aW5nIFBhcnRpZXMgYW5kIG9ubHkgaW4gYWNjb3Jk
YW5jZSB3aXRoIHRoZSBDZXJ0aWZpY2F0ZSBQb2xpY3kgZm91bmQgYXQgaHR0cHM6
b3NpdG9yeS8wgLy9sZXRzZW5jcnlwdC5vcmcvcmVwgEEBgorBgEEAdZ5AgQCBIH1
BIHyAPAAdgBVgdTCFpA2AUrqC5tXPFPwwOQ4eHAlCBcvo6odBxPTDAAAAWMko+bm
AAAEAwBHMEUCIDrFrnfdS2r2s/jX42IFlvq57COkYSmFDye8RsDclEEtAiEA60jA
i8esMVLGzNYdLL1/mjOwBrmIawBGhmiPcsfGeiwAdgApPFGWVMg5ZbqqUPxYB9S3
b79Yeily3KTDDPTlRUf0eAAAAWMko+bFAAAEAwBHMEUCIBGyg9g0cFfMGcq3tLO1
T5k7BuElqaOWdddLFHiTah+KAiEAv/GkrPeBGsZqX24W0HUalbIiLRVtbmFXeVON
kE0pYXwwDQYJKoZIhvcNAQELBQADggEBABwfZyvWmPvTBFSkJ2Hgu2i+yl+8QVTg
7ArLtpqnjO3e0IrveKQpFGRYaqTjC4FtuMijaPec5he6RqlrzlGEae0SK9ck5ZJF
Je86mtKr8LCr2tzK++Lgmwg61c8FILihuLW9mKcxnWHczD+MvVMemLaViBZigBjy
q5ShvXeRJG4IzA1jWllLaDXd35oDX8LWu1UVJDH6fIB/T33gVVMsftJc6tPiochx
XqMAeMMyVh9FByBg+KPL3ALChH+2m9sJQEDlao3ldLId1/R/p6CgpNcMcQKr89TF
mnki3xw8oZovFjkf0g+wB/mYjADj50Bibo3t4RArQ2fXIDiA3U30cgA=
-----END CERTIFICATE-----
[Thu May  3 06:15:11 UTC 2018] Your cert is in  /root/.acme.sh/api.datacenter1.example.com/api.datacenter1.example.com.cer
[Thu May  3 06:15:11 UTC 2018] Your cert key is in  /root/.acme.sh/api.datacenter1.example.com/api.datacenter1.example.com.key
[Thu May  3 06:15:12 UTC 2018] The intermediate CA cert is in  /root/.acme.sh/api.datacenter1.example.com/ca.cer
[Thu May  3 06:15:12 UTC 2018] And the full chain certs is there:  /root/.acme.sh/api.datacenter1.example.com/fullchain.cer
```

### Deploy the certificate
The following steps deploy the certificate and private key to HAProxy and then reloads. More details here: https://github.com/Neilpang/acme.sh/tree/master/deploy

```
[root@k8s-gateway-0 ~]# export DEPLOY_HAPROXY_PEM_PATH=/etc/haproxy
[root@k8s-gateway-0 centos]# acme.sh --deploy -d api.datacenter1.example.com --deploy-hook haproxy
[Fri May  4 16:02:12 UTC 2018] Full path to PEM /etc/haproxy/api.datacenter1.example.com.pem
[Fri May  4 16:02:12 UTC 2018] Certificate successfully deployed
[Fri May  4 16:02:12 UTC 2018] Run reload: /usr/sbin/service haproxy restart
Redirecting to /bin/systemctl restart haproxy.service
[Fri May  4 16:02:12 UTC 2018] Reload success!
[Fri May  4 16:02:12 UTC 2018] Success
```

### Automatic renewals
When acme.sh was installed (see above), it also installed a cron job. That cron job will monitor all certificates on the gateway (there's only one based on this process) and automatically renew them before they expire. This means you should never have to worry about monitoring the certificates or renewing them.

## Security groups and port assignments (reference)
The HEAT templates create and configure default security groups that expose web ports (80, 443), 7443 for `kubectl` API access and 8000-9000 for general use. Review the HEAT templates or the security groups for more details.
