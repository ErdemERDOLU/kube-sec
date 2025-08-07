class ReportGenerator:
    def __init__(self):
        self.reports = []

    def generate_report(self, vulnerabilities):
        report = {
            'total_vulnerabilities': len(vulnerabilities),
            'vulnerabilities': vulnerabilities
        }
        self.reports.append(report)
        return report

    def save_report(self, report, filename):
        with open(filename, 'w') as file:
            file.write(str(report))  # You may want to format this as JSON or another format
        print(f'Report saved to {filename}')