# Excalidraw: a live Parallax stress demonstration

This demonstration uses the real [Excalidraw application](https://github.com/excalidraw/excalidraw), pinned to `2df993fb397dd6d64625908c9c10337727617f6f`. The upstream MIT license remains with its source. This is a local experimental change, not an upstream release or an endorsement by Excalidraw.

## The task

Add find-and-replace to the existing canvas search. A person should be able to inspect matches, replace one occurrence or all eligible occurrences, and undo a batch in one step. The change must preserve text/container bindings, respect locked elements, handle literal replacement text, and keep existing search behavior working.

The test scene is a distributed commerce architecture, with repeated service names, grouped and bound labels, arrows, and a locked reference legend. The result must work inside the actual editor.

## Evidence policy

- Freeze acceptance criteria and independent tests before implementation starts.
- Run real native providers through Parallax's isolated execution pipeline.
- Preserve original upstream source and every failed attempt.
- Keep independent acceptance inputs outside agent-editable checkouts.
- Distinguish passing checks, independent model review, human approval, and application.
- Keep provider cost unknown when native tools do not report it.
- No upstream push, publication, external collaboration session, or production deployment is part of this demonstration.

## Local working files

The ignored `output/showcase/` folder contains the upstream clone, private runtime state, dependency tools, and raw local evidence. Runtime credentials must not be copied into this folder's committed documents. Reproducible acceptance material and the scene live beside this README.

Status: setup and acceptance preparation in progress. No successful implementation or end-to-end verification is claimed yet.
