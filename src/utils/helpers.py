def load_config(config_path):
    import yaml
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    return config

def format_output(vulnerabilities):
    formatted = []
    for vulnerability in vulnerabilities:
        formatted.append(f"Vulnerability: {vulnerability['name']}, Severity: {vulnerability['severity']}")
    return "\n".join(formatted)
