# Changelog

All notable changes to the GLPIADmit plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-01

### Added
- Automated AD user creation from GLPI Service Catalog tickets
- Asynchronous queue processing via CronTask (every 60 seconds)
- Atomic locking to prevent duplicate processing
- Duplicate detection (sAMAccountName and email) before user creation
- Automatic password generation (16 chars, CSPRNG, Fisher-Yates shuffle)
- Forced password change on first login (pwdLastSet=0)
- Automatic rollback on partial creation failure
- Private followup with credentials (technicians only)
- Public followup with generic confirmation (requester visible)
- Ticket status update on success (Resolved) and error (Pending)
- Retry mechanism with permanent vs transient error detection (up to 3 attempts)
- Manual Retry and Force Retry actions in queue item detail page
- GLPIADmit tab on Ticket detail page showing queue item status
- Plugin configuration page with Test Connection button (5s throttle)
- GLPIKey encryption for AD bind password (SECURED_CONFIGS)
- LDAP injection protection via ldap_escape() (RFC 4514/4515)
- Defense in depth: input sanitization (TicketHook) + output sanitization (ADService)
- Accent removal via intl transliterator with iconv fallback
- AD group membership assignment (non-blocking)
- Connection reuse within CronTask cycle
- Reconnect on connection errors
- Comprehensive logging to files/_log/glpiadmit.log
- Docker Compose development environment with Samba AD DC
- Full documentation (8 topic files + consolidated development guide)
