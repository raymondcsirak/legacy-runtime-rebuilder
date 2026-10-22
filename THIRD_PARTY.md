# Patch provenance and credits

The CLI and tests are original MIT-licensed code. No PHP source tree, source patch, vendor package, private operational script, or production report is bundled in this repository.

`runtime_rebuilder/catalog.json` identifies public source packaging published by Ondřej Surý. The CLI downloads each archive over HTTPS and verifies its pinned SHA256 before reading it. It selects individual patches by their SHA256. Those hashes were checked against the source archives during preparation of this project. Recheck publisher source indexes and signatures when updating the catalog.

Security patches credit Arnaud Le Blanc and Ilija Tovilo. Legacy adaptations and prerequisites include work by Remi Collet and upstream PHP contributors. Preserve patch headers and attribution in source rebuilds.

- [Official PHP advisory](https://www.php.net/archive/2026.php#2026-10-21-5)
- [PHP 7.4 minimal backport](https://github.com/php/php-src/commit/712e60f9edfd03f0960fc4fc3c2c375f42b90aa2)
- [Surý Ubuntu source-package repository](https://ppa.launchpadcontent.net/ondrej/php/ubuntu/pool/main/)
- [PHP license](https://github.com/php/php-src/blob/PHP-7.4-CVE-2026-109618-109619/LICENSE)
- [Zend Engine license](https://github.com/php/php-src/blob/PHP-7.4-CVE-2026-109618-109619/Zend/LICENSE)

Downloaded source and patches retain their original licenses. The MIT license in this repository does not relicense them. This project is independent of PHP, Zend, Canonical, Remi, and Surý and claims no endorsement.
