# Security

PatchWatch runs target code only inside Docker and never automatically merges or publishes its output. Read [the threat model](docs/threat-model.md) before processing unfamiliar repositories.

Report suspected vulnerabilities through GitHub private vulnerability reporting when enabled, or contact the repository owner privately. Do not include credentials, private repository contents, or sensitive logs in public issues.

Only the latest v1 release is maintained. Review generated patches and run your own CI before applying them to production code.
