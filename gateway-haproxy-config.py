#!/usr/bin/env python

## run the following from a cron to update the haproxy config
# python gateway_config.py | sudo tee /etc/haproxy/haproxy.cfg
# sudo service haproxy restart

import os
import requests
import jinja2

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

KUBERNETES_MASTER_PORT_LISTEN = 7443
# the next two constants come from openstack for one of the master nodes
KUBERNETES_MASTER_PORT = 6443
KUBERNETES_MASTER_IP = "10.0.20.7" # update with the private IP of one of the master nodes
KUBECTL_HOST = "https://%s:%d" % (KUBERNETES_MASTER_IP, KUBERNETES_MASTER_PORT)
KUBECTL_TOKEN = ""  # JWT, not base64 encoded. Get this from the serviceaccount secret
KUBECTL_VERIFY_SSL = False
HAPROXY_CONFIG_TEMPLATE_FILE = "haproxy.j2"

def get_haproxy_config_template():
    with open(os.path.join(__location__, HAPROXY_CONFIG_TEMPLATE_FILE), 'r') as myfile:
        data = myfile.read()
    return jinja2.Template(data)

def get_k8s_resources(resource):
    """use the k8s API to get node details"""
    url = "%s/api/v1/%s" % (KUBECTL_HOST, resource)
    headers = {'user-agent': 'gateway-config', 'Accept': 'application/json', 'Authorization': 'Bearer %s' % KUBECTL_TOKEN}
    services_request = requests.get(url, headers=headers, verify=KUBECTL_VERIFY_SSL)
    if services_request.status_code != 200:
        raise Exception(services_request.content)
    return services_request.json()['items']

def get_endpoints_for_loadbalancers():
    load_balanced_endpoints = []
    services = get_k8s_resources('services')
    endpoints = get_k8s_resources('endpoints')
    for service in services:
        for endpoint in endpoints:
            if (service['metadata']['name'] == endpoint['metadata']['name']
                and service['metadata']['namespace'] == endpoint['metadata']['namespace']
                and service['spec']['type'] == 'LoadBalancer'):
                if endpoint['subsets']:
                    for subset in endpoint['subsets']:
                        for port in service['spec']['ports']:
                            if port['port'] in [80, 443, 7443] and 'ingress' not in service['metadata']['name']:
                                continue
                            gateway_endpoint = {}
                            gateway_endpoint['name'] = "%s-%d" % (service['metadata']['name'].replace(" ", "-"), port['port'])
                            gateway_endpoint['bind'] = "0.0.0.0:%d" % port['port']
                            gateway_endpoint['mode'] = "%s" % port['protocol'].lower()
                            gateway_endpoint['balance'] = 'leastconn'
                            gateway_endpoint['servers'] = []
                            server_number = 0
                            if 'addresses' in subset:
                                for address in subset['addresses']:
                                    gateway_endpoint['servers'].append("server srv%s %s:%d" % (server_number, address['ip'], port['targetPort']))
                                    server_number += 1
                            load_balanced_endpoints.append(gateway_endpoint)
    return load_balanced_endpoints

def get_endpoint_for_masters():
    nodes = get_k8s_resources('nodes')
    master_endpoint = {}
    master_endpoint['name'] = "%s-%d" % ("master", KUBERNETES_MASTER_PORT_LISTEN)
    master_endpoint['bind'] = "0.0.0.0:%d" % KUBERNETES_MASTER_PORT_LISTEN
    master_endpoint['mode'] = "tcp"
    master_endpoint['balance'] = 'leastconn'
    master_endpoint['servers'] = []
    for node in nodes:
        if "node-role.kubernetes.io/master" in node['metadata']['labels'] and node['metadata']['labels']['node-role.kubernetes.io/master'] == 'true':
            for address in node['status']['addresses']:
                if address['type'] == "InternalIP":
                    master_endpoint['servers'].append("server %s %s:%d" % (node['metadata']['name'].replace(" ", "-"), address['address'], KUBERNETES_MASTER_PORT))
    return master_endpoint

def get_haproxy_config():
    load_balanced_endpoints = get_endpoints_for_loadbalancers()
    haproxy_config = get_haproxy_config_template().render(services=load_balanced_endpoints, master=get_endpoint_for_masters())
    return haproxy_config

def main():
    print(get_haproxy_config())

if __name__ == "__main__":
    main()