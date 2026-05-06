---
id: prefer-temp-script
title: Prefer Temp Script on Windows
tags: [windows, shell, powershell, python]
project_types: [coding, debugging, automation]
priority: 90
confidence: 0.92
layer: domain
domain_scope: [windows, shell, powershell]
stability: stable
conflicts_with: []
valid_until: 2027-12-31
review_after: 2026-12-31
last_validated: 2026-04-22
---
When command logic becomes complex on Windows, write a short helper under `.tmp/` rather than forcing nested quoting into one PowerShell command.
