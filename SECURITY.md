# Security Policy

## Scope

This project is a demonstration Linux server deployment and monitoring toolkit.

It includes:

- Linux system monitoring
- Service health checks
- Network diagnostics
- PostgreSQL persistence
- Docker Compose deployment
- Nginx security headers
- Automated database backups

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately to the repository maintainer rather than opening a public issue.

Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested mitigation, if available

## Security Practices

The project follows several security-oriented practices:

- Secrets are stored in `.env` and excluded from Git.
- PostgreSQL is not publicly exposed by the default Docker Compose configuration.
- The application container runs as a non-root user.
- Docker images use minimal base images where practical.
- Nginx sends common security headers.
- Database backups are gzip-compressed and excluded from Git.
- Automated tests run through GitHub Actions.
- Docker Compose configuration is validated in CI.

## Limitations

This project is intended for learning, demonstration, and development purposes.

A production deployment should additionally consider:

- TLS certificates
- Secret management such as Vault or cloud secret managers
- Firewall rules
- Network segmentation
- Centralized logging
- Monitoring and alerting infrastructure
- Container image vulnerability scanning
- Dependency update automation
- Regular backup restoration testing
