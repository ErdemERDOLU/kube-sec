class K8sScanner:
    def __init__(self, kube_client):
        self.kube_client = kube_client

    def scan_deployment(self, deployment_name, namespace):
        # Logic to scan the specified deployment for vulnerabilities
        deployment = self.kube_client.apps_v1.read_namespaced_deployment(deployment_name, namespace)
        vulnerabilities = self.list_vulnerabilities(deployment)
        return vulnerabilities

    def list_vulnerabilities(self, deployment):
        vulnerabilities = []
        # Pod Security Checks
        if not deployment.spec.template.spec.security_context:
            vulnerabilities.append("Deployment does not have a security context.")
        if any(container.security_context is None for container in deployment.spec.template.spec.containers):
            vulnerabilities.append("One or more containers do not have a security context.")
        for container in deployment.spec.template.spec.containers:
            # 1. Image tag latest kontrolü
            if ":latest" in container.image:
                vulnerabilities.append(f"Container {container.name} uses 'latest' image tag.")
            # 2. Resource limits/requests kontrolü
            resources = getattr(container, 'resources', None)
            if not resources or not getattr(resources, 'limits', None) or not getattr(resources, 'requests', None):
                vulnerabilities.append(f"Container {container.name} does not have resource limits/requests defined.")
            # 3. Env var ile secret kontrolü (örnek: password, secret, key)
            for env in getattr(container, 'env', []) or []:
                if any(word in (env.name or '').lower() for word in ['password', 'secret', 'key', 'token']):
                    vulnerabilities.append(f"Container {container.name} has sensitive info in env var: {env.name}")
            # 4. HostPath volume kontrolü
            for vol in getattr(deployment.spec.template.spec, 'volumes', []) or []:
                if getattr(vol, 'host_path', None):
                    vulnerabilities.append(f"Deployment uses hostPath volume: {vol.name}")
            # 5. readOnlyRootFilesystem kontrolü
            if container.security_context:
                if not getattr(container.security_context, 'read_only_root_filesystem', False):
                    vulnerabilities.append(f"Container {container.name} does not have readOnlyRootFilesystem enabled.")
                # 6. Capabilities kontrolü
                caps = getattr(container.security_context, 'capabilities', None)
                if caps:
                    add_caps = getattr(caps, 'add', []) or []
                    for cap in add_caps:
                        if cap in ['NET_ADMIN', 'SYS_ADMIN']:
                            vulnerabilities.append(f"Container {container.name} adds dangerous capability: {cap}")
                # 9. AllowPrivilegeEscalation kontrolü
                if getattr(container.security_context, 'allow_privilege_escalation', True):
                    vulnerabilities.append(f"Container {container.name} allows privilege escalation.")
            # 7. Liveness/readiness probe kontrolü
            if not getattr(container, 'liveness_probe', None):
                vulnerabilities.append(f"Container {container.name} does not have livenessProbe defined.")
            if not getattr(container, 'readiness_probe', None):
                vulnerabilities.append(f"Container {container.name} does not have readinessProbe defined.")
        # 8. ServiceAccount kontrolü
        sa = getattr(deployment.spec.template.spec, 'service_account_name', None)
        if not sa or sa == 'default':
            vulnerabilities.append("Deployment uses default service account.")
        # Network Policy Checks
        namespace = deployment.metadata.namespace
        try:
            net_policies = self.kube_client.networking_v1.list_namespaced_network_policy(namespace)
            if not net_policies.items:
                vulnerabilities.append(f"No NetworkPolicy found in namespace {namespace}.")
        except Exception as e:
            vulnerabilities.append(f"Error checking NetworkPolicy: {str(e)}")
        return vulnerabilities
