---
type: Component
title: Store
description: File I/O for ~/.archie: frontmatter, fences, atomic writes, tombstones.
resource: archie/store/
status: planned
tags: [component]
---

The only module that writes files. Enforces the [fence rule](../principles/fence-rule.md) and [files are the source of truth](../principles/files-source-of-truth.md). Design: [DESIGN §4](../../docs/DESIGN.md#4-storage-layout).
