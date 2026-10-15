# Changelog

## 2026-10-16

### Added

- The owner can add and remove bot users from IRC. A role may be set; leaving it out stores a bot user, the lowest access.
- One nick can hold a position on more than one site. Admins set someone else's site and position with `.update`.
- News stores a title, or the page heading when the title is left out. Reddit posts keep the real heading.
- Commands other than `.help` run only while the nick is identified with NickServ. A quit drops that confirmation, so a disconnected nick cannot be taken over.

### Changed

- `.help` and `.help admin` from a channel are sent in a private message.
- `.registered` is an admin table of date, site, user, and position.
- Bans for the same nick are one row: the first date, then each site and reason. A site from another day shows a short date beside that site.
- A deleted news number is used again by the next addition.
- Member commands are grouped on `.help`. Admin commands are on `.help admin`. `.reconnect` and `.exit` stay owner-only and are not listed there.
- A nick without access to a command gets no reply.

### Fixed

- Settings are read only from this bot's `.env`. Startup does not send a bouncer connect or a later nick change.
- Private messages are handled for the connected nick. Bouncer playback lines are not run as commands.
- A placeholder Reddit title such as "reddit" is replaced with the post heading.
